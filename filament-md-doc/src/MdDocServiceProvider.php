<?php

namespace MdDoc\FilamentMdDoc;

use Illuminate\Support\ServiceProvider;
use Livewire\Livewire;
use MdDoc\FilamentMdDoc\Livewire\DocumentEditor;

class MdDocServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->mergeConfigFrom(__DIR__ . '/../config/md-doc.php', 'md-doc');
    }

    public function boot(): void
    {
        $this->loadViewsFrom(__DIR__ . '/../resources/views', 'md-doc');

        $this->loadRoutesFrom(__DIR__ . '/../routes/web.php');

        $this->publishes([
            __DIR__ . '/../config/md-doc.php' => config_path('md-doc.php'),
        ], 'md-doc-config');

        $this->publishes([
            __DIR__ . '/../resources/css' => public_path('vendor/md-doc/css'),
            __DIR__ . '/../resources/js'  => public_path('vendor/md-doc/js'),
        ], 'md-doc-assets');

        Livewire::component('md-doc-document-editor', DocumentEditor::class);
    }
}
