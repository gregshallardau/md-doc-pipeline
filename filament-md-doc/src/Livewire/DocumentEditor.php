<?php

namespace MdDoc\FilamentMdDoc\Livewire;

use Filament\Notifications\Notification;
use Livewire\Attributes\On;
use Livewire\Component;
use MdDoc\FilamentMdDoc\MdDocPlugin;
use MdDoc\FilamentMdDoc\Services\ConfigResolver;
use MdDoc\FilamentMdDoc\Services\CssResolver;
use MdDoc\FilamentMdDoc\Services\FileLockService;
use MdDoc\FilamentMdDoc\Services\FilesystemScanner;

class DocumentEditor extends Component
{
    // ── File state ─────────────────────────────────────────────────────────────
    public string $path        = '';
    public string $content     = '';
    public string $fileType    = 'md';
    public string $activeTab   = 'preview';

    // ── Derived data ───────────────────────────────────────────────────────────
    public array  $configLayers      = [];
    public array  $mergedConfig      = [];
    public string $resolvedCss       = '';
    public string $cssSource         = '';
    public array  $includedTemplates = [];
    public array  $fileTree          = [];

    // ── Lock state ────────────────────────────────────────────────────────────
    /** Secret key issued when this session acquired the lock. Null = no lock held. */
    public ?string $lockKey       = null;
    /** Whether this session is in read-only mode (locked by someone else). */
    public bool    $isReadOnly    = false;
    /** Display name of whoever holds the lock (null when unlocked or we hold it). */
    public ?string $lockOwner     = null;
    /** Heartbeat interval in ms — JS polls at this rate to keep the lock alive. */
    public int     $lockHeartbeatMs = 0;

    // ── Services ───────────────────────────────────────────────────────────────
    protected FilesystemScanner $scanner;
    protected ConfigResolver    $configResolver;
    protected CssResolver       $cssResolver;
    protected FileLockService   $lockService;

    public function boot(): void
    {
        $plugin               = filament()->getPlugin('md-doc');
        $this->scanner        = new FilesystemScanner($plugin->getWorkspacePath());
        $this->configResolver = new ConfigResolver();
        $this->cssResolver    = new CssResolver();
        $this->lockService    = new FileLockService();

        $ttl = (int) config('md-doc.lock_ttl_minutes', 10);
        // Heartbeat at half the TTL so the lock doesn't expire between beats
        $this->lockHeartbeatMs = ($ttl * 60 * 1000) / 2;
    }

    public function mount(string $path = ''): void
    {
        $this->fileTree = $this->scanner->scan();

        if ($path !== '') {
            $this->loadFile($path);
        }
    }

    // ── File loading ───────────────────────────────────────────────────────────

    public function loadFile(string $path): void
    {
        // Release any lock held on the previous file before loading a new one
        $this->releaseLock();

        $this->path     = $path;
        $this->content  = $this->scanner->read($path);
        $this->fileType = $this->detectFileType($path);

        $this->acquireLock($path);
        $this->refreshDerivedData();
    }

    // ── Save ───────────────────────────────────────────────────────────────────

    public function save(): void
    {
        if ($this->isReadOnly) {
            Notification::make()->title('File is locked by ' . $this->lockOwner)->danger()->send();
            return;
        }

        // Verify we still hold the lock (could have expired)
        if ($this->lockKey && !$this->lockService->isLockedByKey($this->path, $this->lockKey)) {
            $this->lockKey    = null;
            $this->isReadOnly = true;
            $this->lockOwner  = $this->lockService->getLock($this->path)?->locked_by;

            Notification::make()
                ->title('Lock expired — file not saved')
                ->body('Another session may have taken over. Please reload.')
                ->danger()
                ->send();
            return;
        }

        $this->scanner->write($this->path, $this->content);
        $this->refreshDerivedData();

        Notification::make()->title('Saved')->success()->send();
    }

    // ── Template navigation ────────────────────────────────────────────────────

    public function openTemplate(string $templatePath): void
    {
        $this->loadFile($templatePath);
    }

    // ── Lock management ────────────────────────────────────────────────────────

    protected function acquireLock(string $path): void
    {
        $userLabel = $this->lockService->currentUserLabel();
        $lockKey   = $this->lockService->acquire($path, $userLabel);

        if ($lockKey !== null) {
            $this->lockKey    = $lockKey;
            $this->isReadOnly = false;
            $this->lockOwner  = null;
        } else {
            $this->lockKey    = null;
            $this->isReadOnly = true;
            $this->lockOwner  = $this->lockService->getLock($path)?->locked_by ?? 'unknown';
        }
    }

    /**
     * Release the lock currently held by this session.
     * Called on file switch, component teardown, and from JS 'release-lock' event.
     */
    #[On('release-lock')]
    public function releaseLock(): void
    {
        if ($this->lockKey && $this->path) {
            $this->lockService->release($this->path, $this->lockKey);
        }
        $this->lockKey    = null;
        $this->isReadOnly = false;
        $this->lockOwner  = null;
    }

    /**
     * Heartbeat: extend the lock TTL.
     * Dispatched by JS setInterval every $lockHeartbeatMs milliseconds.
     */
    #[On('lock-heartbeat')]
    public function onHeartbeat(): void
    {
        if (!$this->lockKey) {
            return;
        }

        if (!$this->lockService->refresh($this->path, $this->lockKey)) {
            // Lock expired between heartbeats — switch to read-only
            $this->lockKey    = null;
            $this->isReadOnly = true;
            $this->lockOwner  = $this->lockService->getLock($this->path)?->locked_by ?? 'unknown';

            Notification::make()
                ->title('Editing lock expired')
                ->body('Your lock timed out. The file is now read-only.')
                ->warning()
                ->send();
        }
    }

    /**
     * Allow re-acquiring the lock when the current holder's lock has expired.
     */
    public function tryStealLock(): void
    {
        if (!$this->isReadOnly) {
            return;
        }

        // Only steal if the existing lock is genuinely expired
        $existing = $this->lockService->getLock($this->path);
        if ($existing !== null) {
            Notification::make()
                ->title('Still locked by ' . $existing->locked_by)
                ->body('The lock expires in ' . $existing->minutesRemaining() . ' min.')
                ->warning()
                ->send();
            return;
        }

        // Expired — try to acquire
        $this->acquireLock($this->path);

        if (!$this->isReadOnly) {
            Notification::make()->title('Lock acquired — you can now edit')->success()->send();
        }
    }

    // ── Content change (from Monaco via Alpine/Livewire) ──────────────────────

    #[On('editor-content-changed')]
    public function onContentChanged(string $content): void
    {
        $this->content = $content;

        if ($this->fileType === 'md') {
            $workspacePath = $this->scanner->getWorkspacePath();
            $fullPath      = $this->scanner->resolveSafe($this->path);

            $configResult       = $this->configResolver->resolveWithContent($fullPath, $workspacePath, $content);
            $this->configLayers = $configResult['layers'];
            $this->mergedConfig = $configResult['merged'];
            $this->includedTemplates = $this->scanner->findIncludes($content, $this->path);
        }
    }

    // ── Derived data ───────────────────────────────────────────────────────────

    protected function refreshDerivedData(): void
    {
        if ($this->path === '') {
            return;
        }

        $workspacePath = $this->scanner->getWorkspacePath();
        $fullPath      = $this->scanner->resolveSafe($this->path);

        if ($this->fileType === 'md') {
            $configResult       = $this->configResolver->resolve($fullPath, $workspacePath);
            $this->configLayers = $configResult['layers'];
            $this->mergedConfig = $configResult['merged'];

            $cssResult         = $this->cssResolver->resolve($fullPath, $workspacePath);
            $this->resolvedCss = $cssResult['css'];
            $this->cssSource   = $cssResult['source'] ?? '';

            $this->includedTemplates = $this->scanner->findIncludes($this->content, $this->path);
        } else {
            $this->configLayers      = [];
            $this->mergedConfig      = [];
            $this->includedTemplates = [];

            if ($this->fileType === 'css') {
                $this->resolvedCss = $this->content;
                $this->cssSource   = $this->path;
            } else {
                $cssResult         = $this->cssResolver->resolve($fullPath, $workspacePath);
                $this->resolvedCss = $cssResult['css'];
                $this->cssSource   = $cssResult['source'] ?? '';
            }
        }
    }

    // ── Helpers ────────────────────────────────────────────────────────────────

    protected function detectFileType(string $path): string
    {
        $base = basename($path);
        if (str_ends_with($base, '.md'))  return 'md';
        if (str_ends_with($base, '.css')) return 'css';
        return 'meta';
    }

    public function render()
    {
        return view('md-doc::document-editor', [
            'workspacePath' => $this->scanner->getWorkspacePath(),
        ])->layout('filament-panels::components.layout.index');
    }
}
