<?php

use Illuminate\Support\Facades\Route;
use MdDoc\FilamentMdDoc\Livewire\DocumentEditor;

/*
 * These routes are loaded by MdDocServiceProvider via loadRoutesFrom().
 * They are grouped under the Filament panel middleware by default.
 * If you need auth, add ->middleware('auth') or use Filament's panel prefix.
 */

Route::get('/md-doc/editor', DocumentEditor::class)
    ->name('md-doc.editor');

Route::get('/md-doc/editor/{path}', DocumentEditor::class)
    ->where('path', '.*')
    ->name('md-doc.editor.path');
