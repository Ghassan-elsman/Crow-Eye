"""Application / files acquisition.

Pick an application - or files and folders - on the live machine or in a
forensic image, see everything that belongs to it (program folder, per-user
data and caches, ProgramData, temp files, Prefetch, shortcuts, registry keys),
and copy it into the case with a chain-of-custody record:

    sources.py    one interface over the live machine and a forensic image
    catalog.py    the applications that can be picked
    footprint.py  what belongs to one application, each item with its reason
    collector.py  the copy: hashes, custody, manifest, searchable working copies

Nothing is moved: the original stays where it is, every copy is hashed and
recorded, and the result lands in ``<case>/app_acquisition/``.
"""
