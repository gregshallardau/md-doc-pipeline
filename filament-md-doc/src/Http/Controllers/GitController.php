<?php

namespace MdDoc\FilamentMdDoc\Http\Controllers;

use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Routing\Controller;
use MdDoc\FilamentMdDoc\Services\FilesystemScanner;
use MdDoc\FilamentMdDoc\Services\GitService;

class GitController extends Controller
{
    /**
     * Return the contents of a file at a specific commit (for the diff viewer).
     * Query: ?path=<relative>&commit=<sha>
     */
    public function fileAtCommit(Request $request): JsonResponse
    {
        $path   = $request->query('path');
        $commit = $request->query('commit');

        if (!$path || !$commit) {
            return response()->json(['error' => 'missing path or commit'], 422);
        }

        $git = $this->git();
        $contents = $git->showFileAtCommit($commit, $path);

        if ($contents === null) {
            return response()->json(['error' => 'file not found at commit'], 404);
        }

        return response()->json(['content' => $contents]);
    }

    protected function git(): GitService
    {
        $plugin    = filament()->getPlugin('md-doc');
        $workspace = $plugin->getWorkspacePath();

        // Walk up from workspace to find the actual repo root (.git marker)
        $current = $workspace;
        while (!is_dir($current . DIRECTORY_SEPARATOR . '.git') && dirname($current) !== $current) {
            $current = dirname($current);
        }
        $repoRoot = is_dir($current . DIRECTORY_SEPARATOR . '.git') ? $current : $workspace;

        return new GitService($repoRoot);
    }
}
