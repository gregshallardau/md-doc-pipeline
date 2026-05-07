<?php

namespace MdDoc\FilamentMdDoc\Resources;

use Filament\Resources\Resource;
use Filament\Tables;
use Filament\Tables\Table;
use Filament\Forms\Form;
use Illuminate\Database\Eloquent\Builder;
use MdDoc\FilamentMdDoc\MdDocPlugin;
use MdDoc\FilamentMdDoc\Services\FilesystemScanner;

class DocumentResource extends Resource
{
    protected static ?string $navigationIcon = 'heroicon-o-document-text';
    protected static ?string $navigationLabel = 'Documents';
    protected static ?string $pluralLabel = 'Documents';
    protected static ?string $slug = 'md-doc-documents';

    /**
     * This resource does not use Eloquent — it reads the filesystem directly.
     * We stub the required model with a plain object collection.
     */
    public static function getModel(): string
    {
        return \stdClass::class;
    }

    public static function form(Form $form): Form
    {
        return $form->schema([]);
    }

    public static function table(Table $table): Table
    {
        $files = static::getFiles();

        return $table
            ->query(fn () => collect($files)->toQuery())
            ->columns([
                Tables\Columns\TextColumn::make('name')
                    ->label('File')
                    ->searchable()
                    ->sortable(),
                Tables\Columns\TextColumn::make('path')
                    ->label('Path')
                    ->searchable(),
                Tables\Columns\TextColumn::make('modified_at')
                    ->label('Modified')
                    ->sortable(),
            ])
            ->actions([
                Tables\Actions\Action::make('edit')
                    ->label('Edit')
                    ->icon('heroicon-o-pencil')
                    ->url(fn (array $record) => route('md-doc.editor', ['path' => $record['path']])),
            ])
            ->defaultSort('path');
    }

    protected static function getFiles(): array
    {
        $plugin = filament()->getPlugin('md-doc');
        $scanner = new FilesystemScanner($plugin->getWorkspacePath());
        return $scanner->listMarkdownFiles();
    }

    public static function getPages(): array
    {
        return [];
    }
}
