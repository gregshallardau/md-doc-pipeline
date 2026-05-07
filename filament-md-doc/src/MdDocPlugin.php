<?php

namespace MdDoc\FilamentMdDoc;

use Filament\Contracts\Plugin;
use Filament\Panel;
use MdDoc\FilamentMdDoc\Resources\DocumentResource;

class MdDocPlugin implements Plugin
{
    protected string $workspacePath = '';

    public static function make(): static
    {
        return app(static::class);
    }

    public function getId(): string
    {
        return 'md-doc';
    }

    public function workspacePath(string $path): static
    {
        $this->workspacePath = $path;
        return $this;
    }

    public function getWorkspacePath(): string
    {
        return $this->workspacePath ?: config('md-doc.workspace_path', base_path('workspace'));
    }

    public function register(Panel $panel): void
    {
        $panel->resources([
            DocumentResource::class,
        ]);
    }

    public function boot(Panel $panel): void
    {
        //
    }
}
