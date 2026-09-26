"""Identity of an explicitly selected data column, independent of its public name."""


def selector_identity(selector):
    """Compare a selected field, independent of renaming or unit conversion."""
    if hasattr(selector, 'model_dump'):
        selector = selector.model_dump(mode='json')
    if selector['kind'] == 'table':
        return ('table', selector['table'], selector['column'], selector.get('where', {}))
    return ('array', selector['array'], selector.get('row_axis', 0), selector.get('component', []))
