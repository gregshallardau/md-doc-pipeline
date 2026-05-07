{{-- Config layers accordion panel --}}
{{-- $layers: array of ['file', 'values'] --}}
{{-- $merged: flat merged config dict --}}

<div class="md-doc-config-panel">

    @if(empty($layers))
        <p class="md-doc-config-empty">No config loaded. Open a .md file to see its inherited config.</p>
    @else

        @foreach($layers as $layer)
        <details class="md-doc-config-layer" open>
            <summary class="md-doc-config-layer-header">
                <span class="md-doc-config-layer-icon">
                    {{ $layer['file'] === 'frontmatter' ? '📝' : '⚙️' }}
                </span>
                <span class="md-doc-config-layer-name">
                    {{ $layer['file'] }}
                </span>
            </summary>
            <div class="md-doc-config-layer-body">
                <table class="md-doc-config-table">
                    @foreach($layer['values'] as $key => $value)
                    <tr>
                        <td class="md-doc-config-key">{{ $key }}</td>
                        <td class="md-doc-config-value">
                            @if(is_array($value))
                                {{ implode(', ', $value) }}
                            @elseif(is_bool($value))
                                {{ $value ? 'true' : 'false' }}
                            @else
                                {{ $value }}
                            @endif
                        </td>
                    </tr>
                    @endforeach
                </table>
            </div>
        </details>
        @endforeach

        {{-- Final merged result --}}
        <details class="md-doc-config-layer md-doc-config-merged">
            <summary class="md-doc-config-layer-header">
                <span class="md-doc-config-layer-icon">✅</span>
                <span class="md-doc-config-layer-name">Merged (final)</span>
            </summary>
            <div class="md-doc-config-layer-body">
                <table class="md-doc-config-table">
                    @foreach($merged as $key => $value)
                    <tr>
                        <td class="md-doc-config-key">{{ $key }}</td>
                        <td class="md-doc-config-value">
                            @if(is_array($value))
                                {{ implode(', ', $value) }}
                            @elseif(is_bool($value))
                                {{ $value ? 'true' : 'false' }}
                            @else
                                {{ $value }}
                            @endif
                        </td>
                    </tr>
                    @endforeach
                </table>
            </div>
        </details>

    @endif

</div>
