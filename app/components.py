# Import the framework
from js import console

from metafor.core import create_effect, create_signal, after_update, before_update, on_dispose, on_mount
from metafor.hooks import create_memo, use_context, use_provider
from metafor.components import For, Portal, Show
from metafor.dom import t
from metafor.core import batch_updates
from metafor.decorators import component, page
from pages.dashboard import Dashboard
from contexts import ThemeContext
from app_state import container, counter_provider

@component()
def Demo(**props):
    print(props)
    return t.p({}, props['children'])

# Counter Component
@page("/counter",
    props={"initial": (int, 2)}
)
def Counter(**props):
    
    theme = use_context(ThemeContext)
    test, set_test = create_signal("test")
    count, set_count = create_signal(props.get("initial", 0))
    
    count_value, set_count_provider = use_provider(container, counter_provider)
  
    def my_batch():
        # Use a temporary variable to hold the current count.
        current_count = count()
        
        batch_updates(lambda: [
            set_count(current_count + 1),
            set_count(current_count + 2),
            set_count(current_count + 3),
            set_test('ontest')
        ])
    
    def increment(evt):
        set_count(count() + 1)
        set_count_provider(count_value() + 1)
    
    def decrement(evt):
        set_count(count() - 1)
        
    def on_test(evt):
        my_batch()
    
    doubled = create_memo(lambda: count() * 2)
    
    # --- Lifecycle Hooks ---

    # on_mount (executed when the component is added to the DOM)
    def on_mounted():
        print("Counter component mounted")

    on_mount(on_mounted)

    # before_update (executed before any attribute or text content updates)
    before_update([count, test], lambda *args: print("Counter component is about to update!"))

    # after_update (executed after any attribute or text content updates)
    after_update(count, lambda: print("Counter component after_update!"))

    # on_dispose (executed when the component is removed from the DOM)
    def dispose_counter():
        print("Counter component disposed!")

    on_dispose(dispose_counter)

    show_home = create_memo(lambda: count() > 2)

    theme = use_context(ThemeContext)
    home_page = Show(when=show_home, children=Dashboard)
    list_items = Show(when=show_home, children=Dashboard)

    # Sample data for cats
    cats, set_cats = create_signal([
        {"id": "Jhd3aiyznGQ", "name": "Keyboard Cat"},
        {"id": "ziAbfPXTKms", "name": "Maru"},
        {"id": "OUtn3pvWmpg", "name": "Henri The Existential Cat"}
    ])

    # State for Switch/Match example
    tab, set_tab = create_signal("home")

    def on_tab_change(tab):
        print(f"Tab changed to: {tab}")
        set_tab(tab)

    # State for Portal example
    show_modal, set_show_modal = create_signal(False)
    def on_modal_change(modal):
        print(f"Modal changed to: {modal}")
        set_show_modal(modal)

    # State for ErrorBoundary example
    trigger_error, set_trigger_error = create_signal(False)

    # --- Lifecycle End ---
    
    context_data = {
        'count': count,
        'set_count': set_count,
        'increment': increment,
        'decrement': decrement,
        'doubled': doubled,
        'test': test,
        'on_test': on_test,
        'theme': theme,
        'data': {'loading': False, 'name': 'Ricardo'},
        'cats': cats,
        'tab': tab,
        'set_tab': on_tab_change,
        'show_modal': show_modal,
        'set_show_modal': on_modal_change,
        'trigger_error': trigger_error,
        'set_trigger_error': set_trigger_error,
        'Modal': Modal,
        'Portal': Portal,
        'Demo': Demo,
    }

    print(f"count: {count()}")

    return t.jsx("jsx/counter.jsx", context=context_data)

# TodoList Component
@page("/todos/:id?")
def TodoList(**props):
    print(f'TodoList Props {props}')
    theme = use_context(ThemeContext)

    todos, set_todos = create_signal([
        {"id": 1, "text": "Learn PyScript", "completed": True},
        {"id": 2, "text": "Build a SolidJS-like framework", "completed": False},
        {"id": 3, "text": "Create amazing web apps with Python", "completed": False}
    ], deep=True)
    
    new_todo, set_new_todo = create_signal("")
    
    def add_todo(event):
        if not new_todo().strip():
            return

        # uses deep reactivity
        todos().append({
            "id": len(todos()) + 1,
            "text": new_todo(),
            "completed": False 
        })
    
        set_new_todo("")
    
    def toggle_todo(todo_id):
        updated_todos = []
        
        for todo in todos():
            if todo["id"] == todo_id:
                todo = todo.copy()
                todo["completed"] = not todo["completed"]

            updated_todos.append(todo)
            
        set_todos(updated_todos)
    
    def handle_key_press(event):
        if event.key == "Enter":
            add_todo(event)
    
    remaining = create_memo(lambda: sum(1 for todo in todos() if not todo["completed"]))
    
    # Create a todo item
    def create_todo_item(todo, index):
        print("Creating todo item: ", todo)
        return t.div( {
            "class_name": lambda: f"todo-item {('completed' if todo['completed'] else '')}",
            "key": str(todo["id"])
        }, [
            t.input({
                "type": "checkbox",
                "class_name": "form-check-input me-2",
                "checked": lambda: "checked" if todo["completed"] else None,
                "@click": lambda e: toggle_todo(todo["id"])
            }),
            t.span({}, todo["text"])
        ])
    
    
    return t.div({"class_name": lambda: f"todo-list theme-{theme()}"}, [
        t.h3({}, "Todo List"),
        
        t.div({"class_name": "todo-input input-group"}, [
            t.input({
                "type": "text",
                "class_name": "form-control",
                "placeholder": "Add new todo",
                "value": new_todo,
                "@keyup": handle_key_press,
                "@input": lambda e: set_new_todo(e.target.value)
            }),

            t.button({
                "class_name": "btn btn-success",
                "@click": add_todo
            }, "Add")
        ]),
        
        # Use the container
        t.div({"class_name": "todo-items"}, 
            For(
                each=todos,
                key=lambda todo, _: todo['id'],
                children=create_todo_item,
            )
        ),
    
        t.div({"class_name": "mt-3"}, [
            lambda: f"{remaining()} items remaining"
        ]),

        Modal(is_open=True, children=t.h4({}, "Portal Content"))
    ])

@component()
def Modal(is_open, children, **props):
    return Show(
        when=is_open,
        children=lambda: Portal('#modal-root', children)
    )