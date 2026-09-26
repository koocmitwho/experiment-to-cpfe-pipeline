"""Serializable error context shared by local command and task boundaries."""
from pathlib import Path


class DiagnosticError(ValueError):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__('; '.join(f"{item['field']}: {item['reason']}" if item.get('field') else item['reason']
                                  for item in diagnostics))


def diagnostic(exc, *, file=None, field=None, stage=None, code=None, suggestion=None):
    reason = str(exc)
    if code is None:
        code = ('file_not_found' if isinstance(exc, FileNotFoundError) else
                'output_exists' if isinstance(exc, FileExistsError) else
                'integrity_mismatch' if any(word in reason.lower() for word in ('integrity', 'drift', 'binding', 'hash')) else
                'invalid_configuration')
    if suggestion is None:
        suggestion = {
            'file_not_found': 'Check the named file and resolve relative paths against the configuration directory.',
            'output_exists': 'Choose a new output directory; preserve the existing attempt.',
            'integrity_mismatch': 'Restore the original verified input/artifact or start a new task for changed data, configuration, code or environment. Do not re-sign the old attempt.',
        }.get(code, 'Correct the named field using its source declaration and rerun the check before execution.')
    filename = getattr(exc, 'filename', None) or file
    return dict(code=code, file=str(Path(filename)) if filename is not None else None,
                field=field, stage=stage, reason=reason, suggestion=suggestion)


def diagnostics_for(exc, *, file=None, field=None, stage=None, **options):
    if isinstance(exc, DiagnosticError):
        return [dict(item, file=item.get('file') or (str(file) if file is not None else None),
                     stage=item.get('stage') or stage,
                     field='.'.join(v for v in (field, item.get('field')) if v) or None)
                for item in exc.diagnostics]
    from pydantic import ValidationError
    if isinstance(exc, ValidationError):
        return [diagnostic(ValueError(item['msg']), file=file,
                           field='.'.join(str(v) for v in ((field,) if field else ()) + item['loc']),
                           stage=stage, **options) for item in exc.errors(include_url=False)]
    return [diagnostic(exc, file=file, field=field, stage=stage, **options)]
