<?php
/** Dependency-free service/component regressions; framework adapters are test doubles. */
namespace Livewire {
    class Component {
        public array $events = [];
        public function dispatch(string $name, ...$args): void { $this->events[] = [$name, $args]; }
    }
}
namespace Filament\Notifications {
    class Notification {
        public static function make(): self { return new self(); }
        public function __call($name, $args): self { return $this; }
    }
}
namespace Illuminate\Support\Facades {
    class DB {
        public static function transaction(callable $fn): void { $fn(); }
    }
    class Cache {
        public static array $values = [];
        public static function forget($key): void { unset(self::$values[$key]); }
        public static function get($key): mixed { return self::$values[$key] ?? null; }
    }
}
namespace MdDoc\FilamentMdDoc\Models {
    class FileLock {
        public static ?object $record = null;
        public static function where(...$args): self { return new self(); }
        public function lockForUpdate(): self { return $this; }
        public function first(): ?object { return self::$record; }
    }
}
namespace {
    use MdDoc\FilamentMdDoc\Services\FilesystemScanner;
    use MdDoc\FilamentMdDoc\Services\FileLockService;
    use MdDoc\FilamentMdDoc\Services\BuildRunner;
    use MdDoc\FilamentMdDoc\Services\CssResolver;
    use MdDoc\FilamentMdDoc\Livewire\DocumentEditor;
    use MdDoc\FilamentMdDoc\Models\FileLock;
    use Illuminate\Support\Facades\Cache;

    require __DIR__ . '/../src/Services/FilesystemScanner.php';
    require __DIR__ . '/../src/Services/FileLockService.php';
    require __DIR__ . '/../src/Services/BuildRunner.php';
    require __DIR__ . '/../src/Services/CssResolver.php';
    require __DIR__ . '/../src/Livewire/DocumentEditor.php';

    function now(): \DateTimeImmutable { return new \DateTimeImmutable(); }
    function config($key, $default = null): mixed { return $GLOBALS['settings'][$key] ?? $default; }
    $checks = 0;
    function check(bool $ok, string $message): void {
        global $checks;
        if (!$ok) throw new \RuntimeException($message);
        $checks++;
    }
    function rejects(callable $fn): void {
        try { $fn(); } catch (\RuntimeException) { check(true, 'rejected'); return; }
        throw new \RuntimeException('Expected rejection');
    }
    class Locks extends FileLockService {
        public function acquire(string $path, string $lockedBy): ?string { return 'key'; }
        public function release(string $path, string $key): void { FileLock::$record = null; }
        public function currentUserLabel(): string { return 'tester'; }
    }
    class Builds extends BuildRunner {
        public int $calls = 0;
        public function build(string $path, string $format = 'pdf'): array {
            $this->calls++;
            return ['token' => 'built', 'format' => $format, 'filename' => 'doc.pdf'];
        }
    }
    class Editor extends DocumentEditor {
        public Builds $builds;
        public function __construct(FilesystemScanner $scanner) {
            $this->scanner = $scanner;
            $this->lockService = new Locks();
            $this->builds = new Builds();
            $this->buildRunner = $this->builds;
        }
        protected function refreshDerivedData(): void {}
    }
    function validLock(): void {
        FileLock::$record = (object) ['lock_key' => 'key', 'expires_at' => now()->modify('+10 minutes')];
    }
    function removeTree(string $path): void {
        if (is_link($path) || is_file($path)) { unlink($path); return; }
        foreach (new \FilesystemIterator($path) as $child) removeTree($child->getPathname());
        rmdir($path);
    }

    $base = sys_get_temp_dir() . '/md-doc-regression-' . bin2hex(random_bytes(8));
    mkdir($base . '/docs', 0700, true);
    mkdir($base . '/docs-private');
    try {
        file_put_contents($base . '/docs/doc.md', 'original');
        file_put_contents($base . '/docs-private/secret.md', 'secret');
        symlink($base . '/docs-private', $base . '/docs/outside');
        symlink($base . '/docs', $base . '/docs/cycle');
        $scanner = new FilesystemScanner($base . '/docs');
        rejects(fn () => $scanner->read('../docs-private/secret.md'));
        rejects(fn () => $scanner->write('../docs-private/new.md', 'bad'));
        rejects(fn () => $scanner->read('outside/secret.md'));
        check($scanner->resolveTemplate('../docs-private/secret.md', $base . '/docs/doc.md') === null, 'unsafe include');
        check(count($scanner->scan()) === 1, 'scan follows symlinks');
        check(count($scanner->listMarkdownFiles()) === 1, 'list follows symlinks');
        $scanner->write('new.md', 'new');
        check($scanner->read('new.md') === 'new', 'safe create');

        $editor = new Editor($scanner);
        $editor->buildToken = 'old';
        $editor->loadFile('./doc.md');
        check($editor->path === 'doc.md', 'canonical file identity');
        check($editor->buildToken === null, 'stale build cleared');
        check($editor->events[0][0] === 'file-loaded' && $editor->events[0][1]['path'] === 'doc.md', 'file switch event');
        validLock();
        $editor->content = 'stale debounce value';
        $editor->save('latest Monaco content', 'doc.md');
        check($scanner->read('doc.md') === 'latest Monaco content', 'save must use snapshot');
        $editor->save('wrong file', 'previous.md');
        check($scanner->read('doc.md') === 'latest Monaco content', 'stale path rejected');
        $editor->onContentChanged('late event', 'previous.md');
        check($editor->content === 'latest Monaco content', 'late event ignored');
        FileLock::$record->expires_at = now()->modify('-1 second');
        $editor->save('expired write', 'doc.md');
        $editor->buildPdf('expired build write', 'doc.md');
        check($scanner->read('doc.md') === 'latest Monaco content', 'expired owner cannot write');
        check($editor->builds->calls === 0, 'expired owner cannot build unsaved snapshot');
        validLock();
        $editor->lockKey = 'wrong-owner';
        $editor->save('wrong owner write', 'doc.md');
        check($scanner->read('doc.md') === 'latest Monaco content', 'wrong owner rejected');
        $editor->lockKey = 'key';
        $editor->buildPdf('fresh build snapshot', 'doc.md');
        check($scanner->read('doc.md') === 'fresh build snapshot', 'build saves snapshot');
        check($editor->builds->calls === 1, 'valid build called');
        $editor->releaseLock();
        $editor->save('after release', 'doc.md');
        check($scanner->read('doc.md') === 'fresh build snapshot', 'released owner cannot save');

        $GLOBALS['settings']['md-doc.build_tmp_dir'] = $base . '/builds';
        $expired = str_repeat('a', 40);
        $active = str_repeat('b', 40);
        mkdir($base . '/builds/' . $expired, 0700, true);
        mkdir($base . '/builds/' . $active);
        file_put_contents($base . '/builds/' . $expired . '/.expires', (string)(time() - 60));
        file_put_contents($base . '/builds/' . $active . '/.expires', (string)(time() + 60));
        symlink($base . '/docs-private', $base . '/builds/' . $expired . '/link');
        Cache::$values['md-doc-build:' . $expired] = ['path' => 'expired'];
        (new BuildRunner())->pruneExpired();
        check(!is_dir($base . '/builds/' . $expired), 'expired build removed');
        check(is_dir($base . '/builds/' . $active), 'active build retained');
        check(is_file($base . '/docs-private/secret.md'), 'cleanup does not follow symlinks');
        check(Cache::get('md-doc-build:' . $expired) === null, 'expired cache removed');
            // CSS theme resolution: PDF theme first, Word-only theme ignored, imports inlined in-workspace.
    $cssRoot = sys_get_temp_dir() . '/md-doc-css-' . bin2hex(random_bytes(4));
    mkdir($cssRoot . '/ws', 0777, true);
    file_put_contents($cssRoot . '/outside.css', 'body { background: url(secret); }');
    file_put_contents($cssRoot . '/ws/_docx-theme.css', 'body { color: red; }');
    file_put_contents($cssRoot . '/ws/_theme.css', 'h1 { color: #123456; }');
    file_put_contents($cssRoot . '/ws/doc.md', '# T');
    $css = (new CssResolver())->resolve($cssRoot . '/ws/doc.md', $cssRoot . '/ws');
    check($css['source'] === '_theme.css' && !str_contains($css['css'], 'red'), 'word-only theme ignored');
    file_put_contents($cssRoot . '/ws/_pdf-theme.css', "@import '_theme.css';\n@import '../outside.css';\nbody { font-size: 11pt; }");
    $css = (new CssResolver())->resolve($cssRoot . '/ws/doc.md', $cssRoot . '/ws');
    check($css['source'] === '_pdf-theme.css', 'pdf theme wins over shared theme');
    check(str_contains($css['css'], '#123456') && str_contains($css['css'], '11pt'), 'import inlined');
    check(!str_contains($css['css'], 'secret') && !str_contains($css['css'], '@import'), 'imports stay in workspace');
    foreach (['_docx-theme.css', '_theme.css', '_pdf-theme.css', 'doc.md'] as $f) { unlink($cssRoot . '/ws/' . $f); }
    unlink($cssRoot . '/outside.css'); rmdir($cssRoot . '/ws'); rmdir($cssRoot);

echo "$checks PHP regression checks passed\n";
    } finally {
        removeTree($base);
    }
}
