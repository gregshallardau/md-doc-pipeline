<?php

namespace MdDoc\FilamentMdDoc\Services;

use Illuminate\Support\Facades\Cache;
use Illuminate\Support\Str;
use RuntimeException;
use Symfony\Component\Process\Process;

class BuildRunner
{
    /**
     * Run `md-doc build <docPath> --output <tmp>` and return a token that can be
     * exchanged for the built file via BuildController::serve().
     *
     * @param  string  $docFullPath   Absolute path to the .md file to build.
     * @param  string  $format        pdf | docx | dotx
     * @return array{token: string, filename: string, format: string}
     *
     * @throws RuntimeException on build failure (stderr captured in message).
     */
    public function build(string $docFullPath, string $format = 'pdf'): array
    {
        if (!file_exists($docFullPath)) {
            throw new RuntimeException("Source file does not exist: {$docFullPath}");
        }

        if (!in_array($format, ['pdf', 'docx', 'dotx'], true)) {
            throw new RuntimeException("Unsupported format");
        }
        $this->pruneExpired();
        $bin     = config('md-doc.md_doc_bin', 'md-doc');
        $token   = Str::random(40);
        $tmpRoot = config('md-doc.build_tmp_dir', sys_get_temp_dir() . '/md-doc-builds');
        $tmpDir  = $tmpRoot . DIRECTORY_SEPARATOR . $token;

        if (!is_dir($tmpDir) && !mkdir($tmpDir, 0700, true) && !is_dir($tmpDir)) {
            throw new RuntimeException("Failed to create build directory: {$tmpDir}");
        }

        $complete = false;
        try {
            // Build the selected source into this token’s private output directory.
            $process = new Process([
                $bin,
                'build',
                $docFullPath,
                '--output', $tmpDir,
                '--format', $format,
            ]);
            $process->setTimeout((float) config('md-doc.build_timeout_seconds', 120));
            $process->run();

            if (!$process->isSuccessful()) {
                throw new RuntimeException(
                    "md-doc build failed (exit {$process->getExitCode()}): "
                    . trim($process->getErrorOutput() ?: $process->getOutput())
                );
            }

            // Locate the built file. md-doc mirrors the source tree under --output, so
            // the result lives somewhere under $tmpDir with the corresponding extension.
            $expectedExt = $format === 'pdf' ? 'pdf' : ($format === 'dotx' ? 'dotx' : 'docx');
            $built       = $this->findBuiltFile($tmpDir, $expectedExt);

            if ($built === null) {
                throw new RuntimeException("Build succeeded but no .{$expectedExt} found in {$tmpDir}");
            }

            // Cache the token → file mapping for retrieval by BuildController
            Cache::put('md-doc-build:' . $token, [
                'path'     => $built,
                'filename' => basename($built),
                'format'   => $format,
            ], now()->addMinutes((int) config('md-doc.build_token_ttl_minutes', 30)));

            file_put_contents($tmpDir . '/.expires', (string) (time() + (int) config('md-doc.build_token_ttl_minutes', 30) * 60));
            $complete = true;
            return [
                'token'    => $token,
                'filename' => basename($built),
                'format'   => $format,
            ];
        } finally {
            if (!$complete) $this->removeDirectory($tmpDir);
        }
    }

    /**
     * Resolve a token to the cached build entry, or null if expired/invalid.
     *
     * @return array{path: string, filename: string, format: string}|null
     */
    public function resolveToken(string $token): ?array
    {
        $this->pruneExpired();
        $entry = Cache::get('md-doc-build:' . $token);
        if (!is_array($entry) || !isset($entry['path']) || !file_exists($entry['path'])) {
            return null;
        }
        return $entry;
    }

    /** Run periodically as well as on requests; recover abandoned builds after a worker crash. */
    public function pruneExpired(): void
    {
        $root = config('md-doc.build_tmp_dir', sys_get_temp_dir() . '/md-doc-builds');
        $abandonedAge = (int) config('md-doc.build_timeout_seconds', 120)
            + (int) config('md-doc.build_token_ttl_minutes', 30) * 60;
        foreach (glob($root . '/*', GLOB_ONLYDIR) ?: [] as $dir) {
            if (is_link($dir) || !preg_match('/^[A-Za-z0-9]{40}$/', basename($dir))) continue;
            $marker = $dir . '/.expires';
            $expired = is_file($marker)
                ? (int) file_get_contents($marker) < time()
                : filemtime($dir) < time() - $abandonedAge;
            if ($expired) {
                Cache::forget('md-doc-build:' . basename($dir));
                $this->removeDirectory($dir);
            }
        }
    }

    protected function removeDirectory(string $dir): void
    {
        if (!is_dir($dir) || is_link($dir)) return;
        foreach (new \FilesystemIterator($dir, \FilesystemIterator::SKIP_DOTS) as $file) {
            if ($file->isDir() && !$file->isLink()) $this->removeDirectory($file->getPathname());
            else @unlink($file->getPathname());
        }
        @rmdir($dir);
    }

    protected function findBuiltFile(string $dir, string $ext): ?string
    {
        $iterator = new \RecursiveIteratorIterator(
            new \RecursiveDirectoryIterator($dir, \FilesystemIterator::SKIP_DOTS)
        );

        foreach ($iterator as $file) {
            if ($file->isFile() && strtolower($file->getExtension()) === strtolower($ext)) {
                return $file->getPathname();
            }
        }
        return null;
    }
}
