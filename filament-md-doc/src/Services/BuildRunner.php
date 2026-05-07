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

        $bin     = config('md-doc.md_doc_bin', 'md-doc');
        $token   = Str::random(40);
        $tmpRoot = config('md-doc.build_tmp_dir', sys_get_temp_dir() . '/md-doc-builds');
        $tmpDir  = $tmpRoot . DIRECTORY_SEPARATOR . $token;

        if (!is_dir($tmpDir) && !mkdir($tmpDir, 0700, true) && !is_dir($tmpDir)) {
            throw new RuntimeException("Failed to create build directory: {$tmpDir}");
        }

        // Build a single document by passing its parent directory plus the filename
        // matched via a single-pass override. Simplest safe approach: invoke md-doc
        // build on the doc dir and post-filter the produced output by source name.
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

        return [
            'token'    => $token,
            'filename' => basename($built),
            'format'   => $format,
        ];
    }

    /**
     * Resolve a token to the cached build entry, or null if expired/invalid.
     *
     * @return array{path: string, filename: string, format: string}|null
     */
    public function resolveToken(string $token): ?array
    {
        $entry = Cache::get('md-doc-build:' . $token);
        if (!is_array($entry) || !isset($entry['path']) || !file_exists($entry['path'])) {
            return null;
        }
        return $entry;
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
