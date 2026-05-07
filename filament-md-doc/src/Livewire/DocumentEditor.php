<?php

namespace MdDoc\FilamentMdDoc\Livewire;

use Filament\Notifications\Notification;
use Livewire\Attributes\On;
use Livewire\Component;
use MdDoc\FilamentMdDoc\MdDocPlugin;
use MdDoc\FilamentMdDoc\Services\ConfigResolver;
use MdDoc\FilamentMdDoc\Services\CssResolver;
use MdDoc\FilamentMdDoc\Services\FilesystemScanner;

class DocumentEditor extends Component
{
    public string $path        = '';
    public string $content     = '';
    public string $fileType    = 'md';
    public string $activeTab   = 'preview';

    public array  $configLayers     = [];
    public array  $mergedConfig     = [];
    public string $resolvedCss      = '';
    public string $cssSource        = '';
    public array  $includedTemplates = [];
    public array  $fileTree          = [];

    protected FilesystemScanner $scanner;
    protected ConfigResolver    $configResolver;
    protected CssResolver       $cssResolver;

    public function boot(): void
    {
        $plugin               = filament()->getPlugin('md-doc');
        $this->scanner        = new FilesystemScanner($plugin->getWorkspacePath());
        $this->configResolver = new ConfigResolver();
        $this->cssResolver    = new CssResolver();
    }

    public function mount(string $path = ''): void
    {
        $this->fileTree = $this->scanner->scan();

        if ($path !== '') {
            $this->loadFile($path);
        }
    }

    public function loadFile(string $path): void
    {
        $this->path    = $path;
        $this->content = $this->scanner->read($path);
        $this->fileType = $this->detectFileType($path);
        $this->refreshDerivedData();
    }

    public function save(): void
    {
        $this->scanner->write($this->path, $this->content);
        $this->refreshDerivedData();

        Notification::make()
            ->title('Saved')
            ->success()
            ->send();
    }

    public function openTemplate(string $templatePath): void
    {
        $this->loadFile($templatePath);
    }

    /**
     * Triggered by JS when the editor content changes (via Alpine event bridged to Livewire).
     * We only refresh derived data (config, CSS, includes) — the preview itself is rendered in JS.
     */
    #[On('editor-content-changed')]
    public function onContentChanged(string $content): void
    {
        $this->content = $content;

        if ($this->fileType === 'md') {
            $workspacePath = $this->scanner->getWorkspacePath();
            $fullPath      = $this->scanner->resolveSafe($this->path);

            $configResult = $this->configResolver->resolveWithContent($fullPath, $workspacePath, $content);
            $this->configLayers  = $configResult['layers'];
            $this->mergedConfig  = $configResult['merged'];
            $this->includedTemplates = $this->scanner->findIncludes($content, $this->path);
        }
    }

    protected function refreshDerivedData(): void
    {
        if ($this->path === '') {
            return;
        }

        $workspacePath = $this->scanner->getWorkspacePath();
        $fullPath      = $this->scanner->resolveSafe($this->path);

        if ($this->fileType === 'md') {
            $configResult = $this->configResolver->resolve($fullPath, $workspacePath);
            $this->configLayers = $configResult['layers'];
            $this->mergedConfig = $configResult['merged'];

            $cssResult         = $this->cssResolver->resolve($fullPath, $workspacePath);
            $this->resolvedCss = $cssResult['css'];
            $this->cssSource   = $cssResult['source'] ?? '';

            $this->includedTemplates = $this->scanner->findIncludes($this->content, $this->path);
        } else {
            $this->configLayers = [];
            $this->mergedConfig = [];

            // For CSS files, the CSS panel shows the file itself
            if ($this->fileType === 'css') {
                $this->resolvedCss = $this->content;
                $this->cssSource   = $this->path;
            } else {
                $cssResult         = $this->cssResolver->resolve($fullPath, $workspacePath);
                $this->resolvedCss = $cssResult['css'];
                $this->cssSource   = $cssResult['source'] ?? '';
            }

            $this->includedTemplates = [];
        }
    }

    protected function detectFileType(string $path): string
    {
        $basename = basename($path);
        if (str_ends_with($basename, '.md')) {
            return 'md';
        }
        if (str_ends_with($basename, '.css')) {
            return 'css';
        }
        return 'meta';
    }

    public function render()
    {
        return view('md-doc::document-editor', [
            'workspacePath' => $this->scanner->getWorkspacePath(),
        ])->layout('filament-panels::components.layout.index');
    }
}
