"""Open a writer workspace without replacing a ledger session."""
from desktop.dialogs.official_writer import OfficialWriterDialog


def open_official_writer(controller):
    if getattr(getattr(controller, 'window', None), 'busy', False):return
    filing = getattr(controller, '_filing_dialog', None)
    if filing is not None and hasattr(filing, 'commit') and not filing.commit():return
    report = getattr(filing, 'report', None);catalog = getattr(filing, 'catalog', None)
    dialog = OfficialWriterDialog(report, catalog, getattr(controller, 'window', None))
    controller._official_writer_dialog = dialog
    try:dialog.exec()
    finally:controller._official_writer_dialog = None
    return dialog.last_export
