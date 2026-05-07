<?php

namespace MdDoc\FilamentMdDoc\Services;

use Symfony\Component\Process\Process;

class GitService
{
    public function __construct(protected string $repoRoot) {}

    /**
     * Whether the configured directory is inside a git repository at all.
     */
    public function isGitRepo(): bool
    {
        return file_exists($this->repoRoot . DIRECTORY_SEPARATOR . '.git')
            || $this->run(['git', 'rev-parse', '--is-inside-work-tree'])['ok'];
    }

    /**
     * Current branch name, or null if detached/unavailable.
     */
    public function currentBranch(): ?string
    {
        $r = $this->run(['git', 'rev-parse', '--abbrev-ref', 'HEAD']);
        if (!$r['ok']) return null;
        $name = trim($r['stdout']);
        return $name === '' || $name === 'HEAD' ? null : $name;
    }

    /**
     * Commits that touched a single file (most recent first).
     *
     * @return list<array{sha: string, short: string, author: string, date: string, subject: string}>
     */
    public function fileHistory(string $relativePath, int $limit = 30): array
    {
        $sep = "\x1f"; // unit separator — unlikely to appear in commit messages
        $r   = $this->run([
            'git', 'log',
            '--max-count=' . $limit,
            '--follow',
            '--pretty=format:%H' . $sep . '%h' . $sep . '%an' . $sep . '%ad' . $sep . '%s',
            '--date=short',
            '--', $relativePath,
        ]);

        if (!$r['ok'] || trim($r['stdout']) === '') {
            return [];
        }

        $commits = [];
        foreach (explode("\n", $r['stdout']) as $line) {
            $parts = explode($sep, $line);
            if (count($parts) !== 5) continue;
            [$sha, $short, $author, $date, $subject] = $parts;
            $commits[] = [
                'sha'     => $sha,
                'short'   => $short,
                'author'  => $author,
                'date'    => $date,
                'subject' => $subject,
            ];
        }
        return $commits;
    }

    /**
     * Show the contents of a file at a specific commit (e.g. for the diff viewer).
     * Returns null when the file did not exist at that commit.
     */
    public function showFileAtCommit(string $sha, string $relativePath): ?string
    {
        $r = $this->run(['git', 'show', $sha . ':' . $relativePath]);
        return $r['ok'] ? $r['stdout'] : null;
    }

    /**
     * Files with uncommitted modifications (staged or unstaged).
     * Returns a set of relative paths from the repo root.
     *
     * @return array<string, bool>  Path keys, all values `true`.
     */
    public function dirtyPaths(): array
    {
        $r = $this->run(['git', 'status', '--porcelain']);
        if (!$r['ok']) return [];

        $dirty = [];
        foreach (explode("\n", trim($r['stdout'])) as $line) {
            if ($line === '') continue;
            // Format: "XY <path>" — first 2 chars are status codes
            $path = trim(substr($line, 3));
            // Handle renames: "from -> to"
            if (str_contains($path, ' -> ')) {
                $path = trim(explode(' -> ', $path)[1]);
            }
            $dirty[$path] = true;
        }
        return $dirty;
    }

    /**
     * Whether a single file has uncommitted changes (vs HEAD).
     */
    public function isDirty(string $relativePath): bool
    {
        $r = $this->run(['git', 'status', '--porcelain', '--', $relativePath]);
        return $r['ok'] && trim($r['stdout']) !== '';
    }

    // ── Internal ──────────────────────────────────────────────────────────────

    /**
     * Run a git subcommand in $repoRoot.
     *
     * @return array{ok: bool, stdout: string, stderr: string}
     */
    protected function run(array $cmd): array
    {
        $process = new Process($cmd, $this->repoRoot);
        $process->setTimeout(15.0);
        try {
            $process->run();
        } catch (\Throwable $e) {
            return ['ok' => false, 'stdout' => '', 'stderr' => $e->getMessage()];
        }

        return [
            'ok'     => $process->isSuccessful(),
            'stdout' => $process->getOutput(),
            'stderr' => $process->getErrorOutput(),
        ];
    }
}
