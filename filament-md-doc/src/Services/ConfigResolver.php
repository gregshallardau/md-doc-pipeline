<?php

namespace MdDoc\FilamentMdDoc\Services;

use Symfony\Component\Yaml\Yaml;
use Symfony\Component\Yaml\Exception\ParseException;

class ConfigResolver
{
    /**
     * Resolve the cascading _meta.yml config for a document.
     *
     * Walks from the document's directory up to the repo root (detected by .git or pyproject.toml),
     * merges each _meta.yml (shallower = lower priority), then applies the document's own
     * YAML frontmatter as the highest-priority layer.
     *
     * Returns:
     *   [
     *     'merged' => [...],
     *     'layers' => [
     *       ['file' => 'workspace/_meta.yml', 'values' => [...]],
     *       ...
     *       ['file' => 'frontmatter', 'values' => [...]],
     *     ]
     *   ]
     */
    public function resolve(string $docFullPath, string $workspacePath): array
    {
        $repoRoot = $this->findRepoRoot($docFullPath, $workspacePath);
        $metaFiles = $this->collectMetaFiles($docFullPath, $repoRoot);

        $layers = [];
        $merged = [];

        foreach ($metaFiles as $metaPath) {
            $values = $this->parseYamlFile($metaPath);
            if (!empty($values)) {
                $relPath = ltrim(str_replace($workspacePath, '', $metaPath), DIRECTORY_SEPARATOR . '/');
                $layers[] = ['file' => $relPath, 'values' => $values];
                $merged = array_merge($merged, $values);
            }
        }

        // Document frontmatter has highest priority
        if (str_ends_with($docFullPath, '.md') && file_exists($docFullPath)) {
            $frontmatter = $this->parseFrontmatter(file_get_contents($docFullPath));
            if (!empty($frontmatter)) {
                $layers[] = ['file' => 'frontmatter', 'values' => $frontmatter];
                $merged = array_merge($merged, $frontmatter);
            }
        }

        return ['merged' => $merged, 'layers' => $layers];
    }

    /**
     * Same as resolve() but accepts raw content for the doc (unsaved edits).
     */
    public function resolveWithContent(string $docFullPath, string $workspacePath, string $content): array
    {
        $repoRoot  = $this->findRepoRoot($docFullPath, $workspacePath);
        $metaFiles = $this->collectMetaFiles($docFullPath, $repoRoot);

        $layers = [];
        $merged = [];

        foreach ($metaFiles as $metaPath) {
            $values = $this->parseYamlFile($metaPath);
            if (!empty($values)) {
                $relPath = ltrim(str_replace($workspacePath, '', $metaPath), DIRECTORY_SEPARATOR . '/');
                $layers[] = ['file' => $relPath, 'values' => $values];
                $merged = array_merge($merged, $values);
            }
        }

        $frontmatter = $this->parseFrontmatter($content);
        if (!empty($frontmatter)) {
            $layers[] = ['file' => 'frontmatter', 'values' => $frontmatter];
            $merged = array_merge($merged, $frontmatter);
        }

        return ['merged' => $merged, 'layers' => $layers];
    }

    /**
     * Extract YAML frontmatter from between leading --- delimiters.
     */
    public function parseFrontmatter(string $content): array
    {
        if (!str_starts_with(ltrim($content), '---')) {
            return [];
        }
        // Find the closing ---
        $stripped = ltrim($content);
        $end = strpos($stripped, "\n---", 3);
        if ($end === false) {
            return [];
        }
        $yaml = substr($stripped, 3, $end - 3);
        try {
            $parsed = Yaml::parse($yaml);
            return is_array($parsed) ? $parsed : [];
        } catch (ParseException) {
            return [];
        }
    }

    /**
     * Strip frontmatter from markdown content, returning just the body.
     */
    public function stripFrontmatter(string $content): string
    {
        if (!str_starts_with(ltrim($content), '---')) {
            return $content;
        }
        $stripped = ltrim($content);
        $end = strpos($stripped, "\n---", 3);
        if ($end === false) {
            return $content;
        }
        return ltrim(substr($stripped, $end + 4));
    }

    /**
     * Collect _meta.yml files from repo root down to the document's directory (root first).
     */
    protected function collectMetaFiles(string $docFullPath, string $repoRoot): array
    {
        $docDir = is_dir($docFullPath) ? $docFullPath : dirname($docFullPath);
        $repoRoot = rtrim($repoRoot, DIRECTORY_SEPARATOR);

        $dirs = [];
        $current = $docDir;
        while (true) {
            $dirs[] = $current;
            if (rtrim($current, DIRECTORY_SEPARATOR) === $repoRoot) {
                break;
            }
            $parent = dirname($current);
            if ($parent === $current) {
                break;
            }
            $current = $parent;
        }

        // Reverse so root comes first (lowest priority)
        $dirs = array_reverse($dirs);

        $metaFiles = [];
        foreach ($dirs as $dir) {
            $candidate = $dir . DIRECTORY_SEPARATOR . '_meta.yml';
            if (file_exists($candidate)) {
                $metaFiles[] = $candidate;
            }
        }

        return $metaFiles;
    }

    /**
     * Walk up from docPath to find the repo root (.git or pyproject.toml marker),
     * but stop no higher than workspacePath.
     */
    protected function findRepoRoot(string $docFullPath, string $workspacePath): string
    {
        $workspacePath = rtrim($workspacePath, DIRECTORY_SEPARATOR);
        $current = is_dir($docFullPath) ? $docFullPath : dirname($docFullPath);

        while (true) {
            if (file_exists($current . DIRECTORY_SEPARATOR . '.git') ||
                file_exists($current . DIRECTORY_SEPARATOR . 'pyproject.toml')) {
                return $current;
            }
            $parent = dirname($current);
            // Stop at workspace path boundary or filesystem root
            if ($parent === $current || strlen($current) <= strlen($workspacePath)) {
                return $workspacePath;
            }
            $current = $parent;
        }
    }

    protected function parseYamlFile(string $path): array
    {
        if (!file_exists($path)) {
            return [];
        }
        try {
            $parsed = Yaml::parseFile($path);
            return is_array($parsed) ? $parsed : [];
        } catch (ParseException) {
            return [];
        }
    }
}
