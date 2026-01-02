from js import console

def global_error_handler(error: Exception, description: str=None):
    import traceback
    traceback.print_exc()
    console.error(f"%c {error.__class__.__name__}: {str(error)}","color: #7b110a; font-family:sans-serif; font-size: 18px")