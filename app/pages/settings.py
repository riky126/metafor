from metafor.decorators import page
from metafor.dom import t


# Settings Component
@page("/settings")
def Settings(**props):
    print('Settings Page')
    
    t.page_title("Settings Page")
    
    return t.div({"class_name": "about"}, [
        t.h2({}, "Settings Page"),
        t.p({}, "This is the setting page.")
    ])