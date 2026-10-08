<?php

namespace MdDoc\FilamentMdDoc\Services;

class CssResolver
{
    /** Same bound as the Python builders: stops runaway or circular @import chains. */
    private const MAX_IMPORT_DEPTH = 5;

    /**
     * Resolve the CSS theme for a document by walking from its directory up to the repo root.
     *
     * At each folder `_pdf-theme.css` comes before the shared `_theme.css`; the deepest folder
     * wins. The Word-only `_docx-theme.css` is not a PDF theme and is ignored. Relative
     * `@import`s are inlined (inside the workspace only) so the preview iframe, which cannot
     * follow them, is styled the way the PDF will be.
     *
     * Returns: ['css' => '...', 'source' => 'relative/path/_pdf-theme.css']
     *          or ['css' => '', 'source' => null] if nothing found.
     */
    public function resolve(string $docFullPath, string $workspacePath): array
    {
        $docDir        = is_dir($docFullPath) ? $docFullPath : dirname($docFullPath);
        $workspacePath = rtrim($workspacePath, DIRECTORY_SEPARATOR);
        $workspaceReal = realpath($workspacePath) ?: $workspacePath;

        $current = $docDir;
        while (true) {
            foreach (['_pdf-theme.css', '_theme.css'] as $filename) {
                $candidate = $current . DIRECTORY_SEPARATOR . $filename;
                if (file_exists($candidate)) {
                    $relPath = ltrim(str_replace($workspacePath, '', $candidate), DIRECTORY_SEPARATOR . '/');
                    $real    = realpath($candidate) ?: $candidate;
                    return [
                        'css'    => $this->inlineImports($real, $workspaceReal),
                        'source' => $relPath,
                    ];
                }
            }

            if (rtrim($current, DIRECTORY_SEPARATOR) === $workspacePath) {
                break;
            }
            $parent = dirname($current);
            if ($parent === $current) {
                break;
            }
            $current = $parent;
        }

        return ['css' => '', 'source' => null];
    }

    /** Replace `@import 'file.css';` with the file's contents, never leaving the workspace. */
    private function inlineImports(string $file, string $workspaceReal, int $depth = 0): string
    {
        $css = (string) file_get_contents($file);

        return (string) preg_replace_callback(
            '/@import\s+(?:url\(\s*)?[\'"]([^\'"]+)[\'"]\s*\)?\s*;/',
            function (array $m) use ($file, $workspaceReal, $depth): string {
                if ($depth >= self::MAX_IMPORT_DEPTH) {
                    return '';
                }
                $target = realpath(dirname($file) . DIRECTORY_SEPARATOR . $m[1]);
                if ($target === false || !is_file($target)
                    || !str_starts_with($target, $workspaceReal . DIRECTORY_SEPARATOR)) {
                    return '';
                }

                return $this->inlineImports($target, $workspaceReal, $depth + 1) . "\n";
            },
            $css
        );
    }
}
