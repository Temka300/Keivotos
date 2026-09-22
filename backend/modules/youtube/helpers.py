"""Source and frozen helper entry, separate from the application event loop."""
def dispatch_helper(arguments, **_):
    if arguments[:1] != ['--youtube-worker']:
        return None
    from modules.youtube.worker import main
    return main(arguments[1:])
