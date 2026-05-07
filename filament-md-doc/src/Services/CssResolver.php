<?php

namespace MdDoc\FilamentMdDoc\Services;

class CssResolver
{
    /**
     * Resolve the CSS theme for a document by walking from its directory up to the repo root.
     *
     * Priority: _pdf-theme.css > _theme.css, deepest directory wins.
     *
     * Returns: ['css' => '...', 'source' => 'relative/path/_pdf-theme.css']
     *          or ['css' => '', 'source' => null] if nothing found.
     */
    public function resolve(string $docFullPath, string $workspacePath): array
    {
        $docDir       = is_dir($docFullPath) ? $docFullPath : dirname($docFullPath);
        $workspacePath = rtrim($workspacePath, DIRECTORY_SEPARATOR);

        $current = $docDir;
        while (true) {
            foreach (['_pdf-theme.css', '_docx-theme.css', '_theme.css'] as $filename) {
                $candidate = $current . DIRECTORY_SEPARATOR . $filename;
                if (file_exists($candidate)) {
                    $relPath = ltrim(str_replace($workspacePath, '', $candidate), DIRECTORY_SEPARATOR . '/');
                    return [
                        'css'    => file_get_contents($candidate),
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
}
