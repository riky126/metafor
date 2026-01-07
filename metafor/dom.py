import pathlib
from typing import Dict, List
from js import document, console

from typing import Dict, List, Any, Union, Callable, Optional, Set
from js import document, console, setTimeout
from pyodide.ffi import create_proxy, JsProxy

from metafor.core import Signal, Effect, track, create_effect, unwrap, get_current_effect, _effects, _trackable, create_signal, on_dispose
from metafor.transpiler import jsx_to_dom_func
from metafor.utils.html import html_sanitize, preserve_whitespace

ChildType = Union[str, int, float, bool, None, Signal, Callable, 'DOMNode', List[Any]]

def load_css(css_path=''):
    try:
        css_file = pathlib.Path(css_path)
        if not css_file.exists():
            console.warn(f"Warning: CSS file not found: {css_path}")
            return ""

        css_content = load_css_as_docstring(css_path)
        return css_content
    except Exception as e:
        console.warn(f"Error loading CSS {css_path}: {e}")
        return ""
    
def load_css_as_docstring(file_path):
    with open(file_path, 'r') as file:
        css_content = file.read()
    
    # Return the content as a docstring (triple-quoted string)
    return f"""{css_content}"""

def add_scope_css(component_id, element, stylesheets):
  
    style_element = document.createElement("style")
    style_element.setAttribute(f"comp-id", component_id)
    
    # Combine all stylesheets and scope them to the component_id
    scoped_css = "\n".join([f"[comp-id='{component_id}'] {{ {css} }}" for css in stylesheets])
    style_element.textContent = scoped_css
    # Set the component_id as an attribute on the element
    element.setAttribute("comp-id", component_id)
    # Append the style element to the component
    element.prepend(style_element)

def add_global_css(component_id, stylesheets):
  
    style_element = document.createElement("style")
    style_element.setAttribute(f"comp-id", component_id)
    
    # Combine all stylesheets and scope them to the component_id
    style_content = "\n".join([f"{css} " for css in stylesheets])
    style_element.textContent = style_content
    
    # existing_styles = document.head.querySelectorAll('style[comp-id]')
    
    document.head.append(style_element)
        
def apply_css(component_id, element, stylesheets):
    if isinstance(stylesheets, str):
        stylesheets = [{'scoped': stylesheets}]

    if isinstance(stylesheets, dict):
        stylesheets = [stylesheets]

    for css in reversed(stylesheets):
        if "scoped" in css:
            add_scope_css(component_id, element, [css["scoped"]])
            
        if "global" in css:
            add_global_css(component_id, [css["global"]])


def sanitize_html(html_content):
    """
    Standalone function to sanitize HTML content
    """
    return html_sanitize(html_content)


class DOMNode:
    def __init__(self, tag: str, props: Dict = None, children: List[ChildType] = None, namespace: str = None, element=None):
        self.tag = tag
        self.props = props or {}
        self.children = children or []
        self.namespace = namespace
        
        if element:
            self.element = element
        elif self.namespace:
            self.element = document.createElementNS(self.namespace, tag)
        elif tag.startswith("svg:"):
            # Handle namespaced tags if passed as "svg:path"
            local_name = tag.split(":")[1]
            self.namespace = "http://www.w3.org/2000/svg"
            self.element = document.createElementNS(self.namespace, local_name)
        else:
            self.element = document.createElement(tag)
            
        self.child_bindings = []
        self.prop_bindings = []
        self.child_nodes = []
        self.mounted = False
        self.input_binding = None
        self.should_sanitize = tag in ["input", "textarea"] and self.props.get("type", "") != "password"
        
        for key, value in self.props.items():
            if key == 'ref':
                self._handle_ref(self.element, value)
                continue

            if (key.startswith("on") or key.startswith("@")) and callable(value):
                event_name = key[2:].lower() if key.startswith("on") else key[1:]
                self._add_event_listener(event_name, value)

            elif callable(value) and not isinstance(value, Signal):
                def create_prop_effect(prop_key, prop_fn):
                    def update_prop():
                        result = track(prop_fn)
                        self._set_prop(prop_key, result)
                    return create_effect(update_prop)
                
                self.prop_bindings.append(create_prop_effect(key, value))

            elif isinstance(value, Signal):
                self.bind_prop(key, value)
            else:
                self._set_prop(key, value)
        
        if tag in ["input", "textarea", "select"] and "value" in self.props and isinstance(self.props["value"], Signal):
            self._setup_input_binding(self.props["value"])
        
        self._process_children(self.children)

    def _add_event_listener(self, event_name, handler):
        # Create a wrapper to ensure the handler is called with the event
        def event_wrapper(event):
            # Handle 0-argument lambdas (e.g. from () => ...)
            import inspect
            try:
                sig = inspect.signature(handler)
                if len(sig.parameters) == 0:
                    handler()
                else:
                    handler(event)
            except ValueError:
                # Built-ins or other callables where signature fails
                handler(event)
        
        proxy = create_proxy(event_wrapper)
        self.element.addEventListener(event_name, proxy)

    def _handle_ref(self, element, value):
        current_effect = get_current_effect()
        if callable(value):
            def set_ref_signal():
                value({"current": element})
            if current_effect and current_effect in _effects:
                _effects[current_effect]["mounts"].append(set_ref_signal)

        elif isinstance(value, dict) or (hasattr(value, '__getitem__') and hasattr(value, '__setitem__')):
            # Accept dict or any dict-like object (including RefHolder)
            def set_ref():
                try:
                    value["current"] = element
                except (TypeError, AttributeError):
                    # Fallback: try setting as attribute if dict assignment fails
                    try:
                        setattr(value, "current", element)
                    except:
                        pass
            if current_effect and current_effect in _effects:
                _effects[current_effect]["mounts"].append(set_ref)
        else:
            raise Exception("Invalid ref type: must be a callable, dictionary, or dict-like object")

    def _set_prop(self, key: str, value: Any):
        if key == "style" and isinstance(value, dict):
            for style_key, style_value in value.items():
                self.element.style.setProperty(style_key, style_value)
        elif key == "class_name" or key == 'classes':
            self.element.className = value
        elif key == "value" and self.tag in ["input", "textarea", "select"]:
            sanitized_value = html_sanitize(value) if self.should_sanitize else value
            self.element.value = str(sanitized_value) if sanitized_value is not None else ""
        elif key == "innerHTML" or key == "html":
            # Always sanitize innerHTML to prevent XSS
            self.set_html(value)
        elif key == "unsafe_html":
            # For cases where you absolutely need to set raw HTML
            raw_html = value.get('__inner_html', '')
            self.set_unsafe_html(raw_html)
        elif key == "role" or key.startswith("aria-"):
            # ARIA attributes must be set using setAttribute
            # Handle boolean values: True -> "true", False -> remove attribute
            # Handle None: remove attribute
            if value is None or value is False:
                self.element.removeAttribute(key)
            elif value is True:
                self.element.setAttribute(key, "true")
            else:
                self.element.setAttribute(key, str(value))
        else:
            # For namespaced elements (like SVG), always use setAttribute
            if self.namespace:
                 self.element.setAttribute(key, str(value))
            else:
                try:
                    setattr(self.element, key, value)
                except:
                    self.element.setAttribute(key, str(value))

    def _setup_input_binding(self, signal: Signal):
        def update_input():
            current_value = track(lambda: signal())
            sanitized_value = html_sanitize(current_value) if self.should_sanitize else current_value
            if self.element.value != str(sanitized_value):
                self.element.value = str(sanitized_value) if sanitized_value is not None else ""
        self.input_binding = create_effect(update_input)

        def handle_input(event):
            new_value = event.target.value
            
            if self.element.type == "number":
                new_value = float(new_value) if new_value else 0
            elif self.element.type == "checkbox":
                new_value = event.target.checked
            elif self.should_sanitize:
                # Apply sanitization on user input
                new_value = html_sanitize(new_value)
                
            signal.set(new_value)

        input_handler = create_proxy(handle_input)
        self.element.addEventListener("input", input_handler)
        self.prop_bindings.append(input_handler)

    def _process_children(self, children):
        if not children:
            return
        if not isinstance(children, list):
            children = [children]
        for child in children:
            self._append_child(child)

    def _append_child(self, child):
        if isinstance(child, DOMNode):
            self.element.appendChild(child.element)
            self.child_nodes.append(child)
            current_effect = get_current_effect()
            if current_effect:
                current_effect.run_mounts()
            child.mounted = True
            return
        
        if isinstance(child, list):
            for item in child:
                self._append_child(item)
            return
        
        if isinstance(child, Signal):
            text_node = document.createTextNode("")
            self.element.appendChild(text_node)
            def update_signal_text():
                value = track(lambda: child())
                text = str(value) if value is not None else ""
                text_node.textContent = preserve_whitespace(text)
            binding = create_effect(update_signal_text)
            self.child_bindings.append(binding)
            return
        
        if callable(child) and not isinstance(child, Signal):
            # Check if callable accepts 0 arguments
            import inspect
            try:
                sig = inspect.signature(child)
                # Check if we can call it with 0 arguments
                try:
                    sig.bind()
                except TypeError:
                    # Requires arguments, treat as static text
                    text_node = document.createTextNode(str(child))
                    self.element.appendChild(text_node)
                    return
            except ValueError:
                pass

            placeholder = document.createComment("dynamic content")
            self.element.appendChild(placeholder)
            current_nodes = []

            def update_dynamic_content():
                nonlocal current_nodes
                new_content = track(child)

                # Remove old nodes
                for node in current_nodes:
                    if isinstance(node, DOMNode):
                        node.remove()
                    else:
                        # Text node or other native node
                        if node.parentNode:
                            node.parentNode.removeChild(node)
                current_nodes.clear()

                if new_content is None:
                    return
                
                # Normalize new_content to list
                items = new_content if isinstance(new_content, list) else [new_content]

                for item in items:
                    # Resolve callables (components, signals)
                    while callable(item) and not isinstance(item, DOMNode):
                        item = item()
                        
                    if item is None:
                        continue
                        
                    if isinstance(item, DOMNode):
                        self.element.insertBefore(item.element, placeholder)
                        current_nodes.append(item)
                        
                        # Handle mounting
                        if not item.mounted:
                            item.mounted = True
                            current_effect = get_current_effect()
                            if current_effect:
                                current_effect.run_mounts()
                    elif isinstance(item, list):
                        # Handle nested lists (e.g. from components returning lists)
                        for sub_item in item:
                             # We need to recurse or just handle simple nested lists of nodes
                             # For simplicity, let's assume it's a list of nodes or strings
                             if isinstance(sub_item, DOMNode):
                                self.element.insertBefore(sub_item.element, placeholder)
                                current_nodes.append(sub_item)
                                if not sub_item.mounted:
                                    sub_item.mounted = True
                                    current_effect = get_current_effect()
                                    if current_effect:
                                        current_effect.run_mounts()
                             else:
                                text_node = document.createTextNode(str(sub_item))
                                self.element.insertBefore(text_node, placeholder)
                                current_nodes.append(text_node)
                    else:
                        new_value = str(item)
                        text_node = document.createTextNode(preserve_whitespace(new_value))
                        self.element.insertBefore(text_node, placeholder)
                        current_nodes.append(text_node)


            binding = create_effect(update_dynamic_content)
            self.child_bindings.append(binding)
            return
        
        text = str(child) if child is not None else ""
        text_node = document.createTextNode(preserve_whitespace(text))
        self.element.appendChild(text_node)

    def bind_prop(self, key: str, signal: Signal):
        def update_prop():
            value = track(lambda: signal())
            self._set_prop(key, value)

        binding = create_effect(update_prop)
        self.prop_bindings.append(binding)

    def set_html(self, html_content):
        """
        Safely set HTML content with sanitization
        """
        sanitized_html = html_sanitize(html_content)
        self.element.innerHTML = sanitized_html
        return self

    def set_unsafe_html(self, html_content):
        """
        Set raw HTML content without sanitization
        USE WITH EXTREME CAUTION - Only for trusted content
        """
        self.element.innerHTML = html_content
        return self

    def remove(self):
        if self.element.parentNode:
            self.element.parentNode.removeChild(self.element)

        for child in self.child_nodes:
            if hasattr(child, 'remove'):
                child.remove()

        for binding in self.child_bindings:
            binding.dispose()

        for binding in self.prop_bindings:
            if isinstance(binding, JsProxy):
                self.element.removeEventListener("input", binding)
            else:
                binding.dispose()
        if self.input_binding:
            self.input_binding.dispose()

        self._remove_styles()
        self.child_bindings = []
        self.prop_bindings = []
        self.child_nodes = []
        self.input_binding = None
        self.mounted = False

    def _remove_styles(self):
        component_id = id(self)
        elements = document.querySelector(f"head style[comp-id='{component_id}']")

        if elements:
            elements.remove()

def render(component_fn: Callable[[], DOMNode], container_id: str) -> Dict:
    container = document.getElementById(container_id)
    if not container:
        console.error(f"Container with id '{container_id}' not found")
        return None
    
    root_node = None
    root_effect = None

    def root_render():
        nonlocal root_node
        # Clear container safely
        container.innerHTML = ""
        result = component_fn()

        if isinstance(result, DOMNode):
            container.appendChild(result.element)
            current_effect = get_current_effect()
            # In root_render, we are called by create_effect, so current_effect MUST be valid
            if current_effect:
                current_effect.run_mounts()
            result.mounted = True
            root_node = result

        return result
    
    root_effect = create_effect(root_render)

    return {
        "effect": root_effect,
        "unmount": lambda: root_effect.dispose() if root_effect else None
    }

def input(signal: Signal, props: Dict = None) -> DOMNode:
    props = props or {}
    props["value"] = signal
    return DOMNode("input", props)

def textarea(signal: Signal, props: Dict = None) -> DOMNode:
    props = props or {}
    props["value"] = signal
    return DOMNode("textarea", props)

def select(signal: Signal, props: Dict = None) -> DOMNode:
    props = props or {}
    props["value"] = signal
    return DOMNode("select", props)

def option(signal: Signal, props: Dict = None) -> DOMNode:
    props = props or {}
    props["value"] = signal
    return DOMNode("option", props)


def create_html_element(tag, props=None, html_content=None):
    """
    Create an element with sanitized HTML content
    """
    element = DOMNode(tag, props or {})
    if html_content is not None:
        element.set_html(html_content)
    return element

class DomBuilder:
    
    _page_title = None
    
    def __getattr__(self, name):
        def _tag(*children, **kwargs):
            return self.generate_tag(name, *children, **kwargs)
    
        return _tag
    
    def _jsx_parse(self, file_path, scope, css=None):
        # Get the caller's frame
        # If css is provided, we tell the transpiler to inject 'css' variable into the root element
        css_var_name = "css" if css is not None else None
        jsx_output = jsx_to_dom_func(file_path, scope, css_variable=css_var_name)
        
        # Import components locally to avoid circular dependency
        from metafor.components import Show, For, Switch, Match, Suspense, ErrorBoundary, Portal
        
        # Context for eval must include all components generated by transpiler
        eval_context = {
            't': t, 
            'Show': Show, 
            'For': For, 
            'Switch': Switch, 
            'Match': Match, 
            'Suspense': Suspense, 
            'ErrorBoundary': ErrorBoundary, 
            'Portal': Portal,
            **scope
        }
        
        if css is not None:
            eval_context['css'] = css

        output = eval(jsx_output, eval_context)
        return output
    
    def _update_document_title(self):
        if self._page_title:
            document.title = self._page_title
            self._page_title = None

    def jsx(self, file_path, context={}, css=None):
        if isinstance(file_path, str) and file_path.lower().endswith(".jsx"):
            return self._jsx_parse(file_path, context, css)        
    
    def page_title(self, title): 
        if self._page_title != title:
            self._page_title = title
    
    def generate_tag(self, tag: str, props: Dict = None, children: List[ChildType] = None, css=None, **kwargs):
        """
            Create a DOM element (similar to JSX/h function in SolidJS)
        """
        tag = tag.lower().strip()

        if kwargs.get("tag"):
            tag = kwargs.pop("tag")
        elif "_" in tag:
            tag = tag.replace("_", "-")

        namespace = kwargs.get("namespace")
        dom_node = DOMNode(tag, props, children, namespace=namespace)

        # Update document title
        self._update_document_title()

        # Add scoped styles if css are provided    
        if css:
            apply_css(id(dom_node), dom_node.element, css) 

        return dom_node

t = DomBuilder()