<?php

namespace MdDoc\FilamentMdDoc\Services;

use RuntimeException;

class FilesystemScanner
{
    public function __construct(protected string $workspacePath)
    {
        $this->workspacePath = rtrim(realpath($workspacePath) ?: $workspacePath, DIRECTORY_SEPARATOR);
    }

    public function getWorkspacePath(): string
    {
        return $this->workspacePath;
    }

    /**
     * Recursively scan workspace, returning a nested array tree.
     * Each node: ['name', 'path' (relative), 'type' (dir|md|meta|css), 'children'?]
     */
    public function scan(): array
    {
        return $this->scanDirectory($this->workspacePath, $this->workspacePath);
    }

    protected function scanDirectory(string $dir, string $root): array
    {
        $items = [];
        $entries = @scandir($dir);
        if ($entries === false) {
            return [];
        }

        foreach ($entries as $entry) {
            if ($entry === '.' || $entry === '..') {
                continue;
            }
            // Skip hidden files and build outputs
            if (str_starts_with($entry, '.')) {
                continue;
            }

            $fullPath = $dir . DIRECTORY_SEPARATOR . $entry;
            $relPath  = ltrim(str_replace($root, '', $fullPath), DIRECTORY_SEPARATOR);

            if (is_dir($fullPath)) {
                $children = $this->scanDirectory($fullPath, $root);
                $items[] = [
                    'name'     => $entry,
                    'path'     => $relPath,
                    'type'     => 'dir',
                    'children' => $children,
                ];
            } else {
                $type = $this->classifyFile($entry);
                if ($type !== null) {
                    $items[] = [
                        'name' => $entry,
                        'path' => $relPath,
                        'type' => $type,
                    ];
                }
            }
        }

        usort($items, fn($a, $b) => $a['type'] === 'dir' ? -1 : ($b['type'] === 'dir' ? 1 : strcmp($a['name'], $b['name'])));

        return $items;
    }

    protected function classifyFile(string $filename): ?string
    {
        if (str_ends_with($filename, '.md')) {
            return 'md';
        }
        if ($filename === '_meta.yml' || $filename === '_merge_fields.yml') {
            return 'meta';
        }
        if (str_ends_with($filename, '.css')) {
            return 'css';
        }
        return null;
    }

    /**
     * Flat list of all .md files (for the Filament table resource).
     * Each entry: ['name', 'path' (relative), 'full_path', 'modified_at']
     */
    public function listMarkdownFiles(): array
    {
        return $this->collectFiles($this->workspacePath, $this->workspacePath, 'md');
    }

    protected function collectFiles(string $dir, string $root, string $type): array
    {
        $results = [];
        $entries = @scandir($dir);
        if ($entries === false) {
            return [];
        }

        foreach ($entries as $entry) {
            if ($entry === '.' || $entry === '..' || str_starts_with($entry, '.')) {
                continue;
            }
            $fullPath = $dir . DIRECTORY_SEPARATOR . $entry;
            if (is_dir($fullPath)) {
                $results = array_merge($results, $this->collectFiles($fullPath, $root, $type));
            } elseif ($this->classifyFile($entry) === $type) {
                $relPath = ltrim(str_replace($root, '', $fullPath), DIRECTORY_SEPARATOR);
                $results[] = [
                    'name'        => $entry,
                    'path'        => $relPath,
                    'full_path'   => $fullPath,
                    'modified_at' => date('Y-m-d H:i', filemtime($fullPath)),
                ];
            }
        }

        return $results;
    }

    /**
     * Safely read a file. Throws if path escapes workspace root.
     */
    public function read(string $relativePath): string
    {
        $fullPath = $this->resolveSafe($relativePath);
        return file_get_contents($fullPath);
    }

    /**
     * Safely write a file. Throws if path escapes workspace root.
     */
    public function write(string $relativePath, string $content): void
    {
        $fullPath = $this->resolveSafe($relativePath);
        file_put_contents($fullPath, $content);
    }

    /**
     * Resolve a relative path to an absolute path, ensuring it stays within workspace root.
     */
    public function resolveSafe(string $relativePath): string
    {
        // Strip leading slash/separator
        $relative = ltrim($relativePath, '/\\');
        $candidate = $this->workspacePath . DIRECTORY_SEPARATOR . $relative;
        $real = realpath($candidate);

        if ($real === false) {
            // File may not exist yet (for write operations) — check the directory
            $dir = realpath(dirname($candidate));
            if ($dir === false || !str_starts_with($dir, $this->workspacePath)) {
                throw new RuntimeException("Path escapes workspace root: {$relativePath}");
            }
            return $candidate;
        }

        if (!str_starts_with($real, $this->workspacePath)) {
            throw new RuntimeException("Path escapes workspace root: {$relativePath}");
        }

        return $real;
    }

    /**
     * Parse `{% include "..." %}` tags from content and resolve each to a path.
     * Returns array of ['name' => '...', 'path' => 'relative/path.md', 'found' => bool]
     */
    public function findIncludes(string $content, string $docRelativePath): array
    {
        preg_match_all('/\{%-?\s*include\s+["\']([^"\']+)["\']\s*-?%\}/', $content, $matches);

        $includes = [];
        $docFullPath = $this->resolveSafe($docRelativePath);

        foreach (array_unique($matches[1]) as $templateName) {
            $resolved = $this->resolveTemplate($templateName, $docFullPath);
            $relPath  = $resolved ? ltrim(str_replace($this->workspacePath, '', $resolved), DIRECTORY_SEPARATOR) : null;
            $includes[] = [
                'name'  => $templateName,
                'path'  => $relPath,
                'found' => $resolved !== null,
            ];
        }

        return $includes;
    }

    /**
     * Resolve a template name using the same search order as md-doc renderer.py's _MarkdownLoader:
     * doc dir → doc/templates/ → ancestor templates/ dirs (deepest first) → workspace root templates/
     */
    public function resolveTemplate(string $templateName, string $docFullPath): ?string
    {
        $docDir = dirname($docFullPath);

        $searchDirs = [$docDir, $docDir . DIRECTORY_SEPARATOR . 'templates'];

        // Ancestor templates/ dirs (deepest first, stop at workspace root)
        $current = dirname($docDir);
        while (strlen($current) >= strlen($this->workspacePath)) {
            $searchDirs[] = $current . DIRECTORY_SEPARATOR . 'templates';
            if ($current === $this->workspacePath) {
                break;
            }
            $current = dirname($current);
        }

        foreach ($searchDirs as $dir) {
            $candidate = $dir . DIRECTORY_SEPARATOR . $templateName;
            if (file_exists($candidate)) {
                return realpath($candidate);
            }
        }

        return null;
    }
}
