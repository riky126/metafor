import inspect
from js import document, console
from typing import Callable, Any, Dict, Optional, List, Tuple, Union
from metafor.core import ChildType, Signal, DOMNode, batch_updates, create_effect, create_signal, _effects, get_current_effect, track, unwrap
from metafor.dom import t

# Show component for conditional rendering
def Show(when: Union[Signal, Callable[[], bool]], 
         children: Callable[[], ChildType], 
         fallback: Optional[ChildType] = None)  -> Callable[[], Optional[ChildType]]:
    """
    Component for conditional rendering based on a condition
    
    Usage: 
    Show({
        "when": signal_or_function,  # Condition to check
        "fallback": optional_component,  # Component to render when condition is False
        "children": component_to_render  # Component to render when condition is True
    })
    """

    if when is None or not children:
        console.error("Show component requires 'when' and 'children' props")
        return t.div({}, ["Invalid Show props"])
    
    def render_content():
        condition = when() if callable(when) else when
        condition = unwrap(condition) # Unwrap if it's a signal
        if condition:
            return children() if callable(children) else children
        elif fallback:
            return fallback() if callable(fallback) else fallback
        return None
    
    return render_content

# For Component with Keyed Reconciliation
def For(each: Union[Signal, Callable[[], List[Any]], List[Any]], 
        children: Callable[[Any, int], ChildType],
        key: Callable[[Any, int], Any] = None,
        fallback: Optional[ChildType] = None) -> Callable[[], ChildType]:
    """
    Optimized component for rendering lists with keyed reconciliation.
    
    Args:
        each: Source of items (Signal, callable, or static list).
        children: Function to render each item, receiving item and index.
        key: Function to generate unique keys for items, receiving item and index. Defaults to index.
        fallback: Optional component to render when the list is empty.
    
    Returns:
        A callable that renders the list or fallback.
    """
    if key is None:
        key = lambda item, i: i
    # Initialize state only once
    state = {
        "container": None,  # DOMNode wrapper for the list
        "node_map": {},    # key -> DOMNode mapping
        "key_list": []     # Ordered list of keys
    }

    def render_list():
        nonlocal state

        # Get current items
        items = track(each) if callable(each) else each
        items = unwrap(items) # Unwrap if it's a signal
        current_items = list(items) if items else []

        # Handle empty list
        if not current_items:
            if state["container"]:
                state["container"].element.innerHTML = ""  # Clear container
            state["node_map"] = {}
            state["key_list"] = []
            return fallback() if callable(fallback) else fallback if fallback else None

        # Initialize container if not present
        if not state["container"]:
            state["container"] = t.div({"style": {"display": "contents"}}, [])
            if get_current_effect():
                state["container"].mounted = True
                get_current_effect().run_mounts()

        parent = state["container"].element
        new_node_map = {}
        new_key_list = []
        nodes_to_remove = set(state["node_map"].keys())

        # Process current items
        for i, item in enumerate(current_items):
            key_value = str(key(item, i))  # Ensure key is string for DOM
            new_key_list.append(key_value)
            nodes_to_remove.discard(key_value)

            # Reuse existing node if possible
            node = state["node_map"].get(key_value)
            if node:
                # Update existing node
                new_child = children(item, i)
                if isinstance(new_child, DOMNode):
                    update_node(node, new_child)
                else:
                    # Convert non-DOMNode to DOMNode
                    node = t.span({"key": key_value}, [str(new_child)])
                    replace_node(parent, node, key_value)
                new_node_map[key_value] = node
            else:
                # Create new node
                child = children(item, i)
                if isinstance(child, DOMNode):
                    child.props["key"] = key_value
                    if not getattr(child, "mounted", False):
                        child.mounted = True
                        if get_current_effect():
                            get_current_effect().run_mounts()
                elif isinstance(child, list):
                    # Handle list of nodes (fragment)
                    child = t.div({"key": key_value, "style": {"display": "contents"}}, child)
                    if get_current_effect():
                         # We need to manually mark children as mounted? 
                         # t.div will process children and if they are DOMNodes, append them.
                         # DOMNode init calls _process_children which appends.
                         # But we are inside an effect, so we might need to trigger mounts?
                         # t.div init does NOT trigger mounts automatically if not tracked?
                         # Actually t.div init happens here.
                         pass
                else:
                    child = t.span({"key": key_value}, [str(child)])
                new_node_map[key_value] = child
                parent.appendChild(child.element)

        # Remove nodes for items no longer present
        for key_value in nodes_to_remove:
            if key_value in state["node_map"]:
                node = state["node_map"][key_value]
                if node.element.parentNode:
                    node.element.parentNode.removeChild(node.element)

        # Reorder nodes to match new order
        reorder_nodes(parent, new_key_list, new_node_map)

        # Update state
        batch_updates(lambda: [
            state.update({"node_map": new_node_map, "key_list": new_key_list})
        ])

        return state["container"]

    def update_node(existing: DOMNode, new_node: DOMNode):
        """Update an existing node's properties and children."""
        # Update attributes
        for prop_name, prop_value in new_node.props.items():
            if prop_name == "key":
                continue
            new_value = prop_value() if callable(prop_value) else prop_value
            if existing.props.get(prop_name) != new_value:
                existing.props[prop_name] = new_value
                if hasattr(existing.element, "setAttribute"):
                    attr_name = "class" if prop_name in ("class_name", "classes") else prop_name.replace("_", "-")
                    existing.element.setAttribute(attr_name, str(new_value))
        
        # Update children
        existing.children = new_node.children
        # Note: Actual child reconciliation depends on DOMNode's internal handling

    def replace_node(parent: Any, new_node: DOMNode, key_value: str):
        """Replace an existing node in the DOM."""
        old_node = state["node_map"].get(key_value)
        if old_node and old_node.element.parentNode:
            parent.replaceChild(new_node.element, old_node.element)
        else:
            parent.appendChild(new_node.element)
        state["node_map"][key_value] = new_node

    def reorder_nodes(parent: Any, key_list: List[str], node_map: Dict[str, DOMNode]):
        """Reorder DOM nodes to match the key list order."""
        for i, key_value in enumerate(key_list):
            node = node_map.get(key_value)
            if node and node.element.parentNode:
                expected_sibling = parent.childNodes[i] if i < parent.childNodes.length else None
                if node.element != expected_sibling:
                    parent.insertBefore(node.element, expected_sibling)

    return render_list


def Match(when: Union[Signal, Callable[[], bool]], 
          children: Callable[[], ChildType]) -> Dict:
    """
    Component that renders when its condition matches
    To be used inside a Switch component
    
    Usage:
    Match({
        "when": signal_or_function,  # Condition to evaluate
        "children": component_to_render  # Component to render when condition is True
    })
    """
    if when is None or not children:
        console.error("Match component requires 'when' and 'children' props")
        return {"when": False, "children": lambda: None, "is_match": False}
    
    # Store the condition and children
    return {
        "when": when,
        "children": children,
        "is_match": False
    }

def Switch(children: List[Dict], fallback: Optional[ChildType] = None) -> Callable[[], Optional[ChildType]]:
    """
    Component for conditional rendering of the first matching case
    
    Usage:
    Switch([
        Match({"when": condition1, "children": component1}),
        Match({"when": condition2, "children": component2}),
        # ...more matches
    ], fallback=fallback_component)
    """
    
    if not children or not isinstance(children, list):
        console.error("Switch component requires a list of Match components")
        return lambda: DOMNode("div", {}, ["Invalid Switch props"])
    
    def render_content():
        # Process each Match case
        for matched in children:
            if not isinstance(matched, dict) or "when" not in matched or "children" not in matched:
                console.error("Switch expects Match components as children")
                continue
                
            # Evaluate the condition
            condition = matched["when"]() if callable(matched["when"]) else matched["when"]
            
            # If condition is true, render this case and stop
            if condition:
                matched["is_match"] = True
                result = matched["children"]() if callable(matched["children"]) else matched["children"]
                return result
            else:
                matched["is_match"] = False
                
        # If no match is found, render the fallback
        if fallback:
            return fallback() if callable(fallback) else fallback
        return None
    
    return render_content


def LoadingIndicator():
    return t.div({}, "Loading...")


def Suspense(resource_state: Signal, # Pass the state signal from create_resource
             fallback: ChildType, 
             children: Callable[[Any], ChildType]): # Children now receives the resolved data

    def render_suspense():
        state = resource_state()
        if state == 'pending':
            return fallback() if callable(fallback) else fallback
        elif state == 'error':
            # Maybe render a specific error component or the fallback
            # You might want access to the error value here
            error_value = resource_state.peek_error() # Hypothetical method
            print(f"Suspense caught error: {error_value}") 
            return fallback() if callable(fallback) else fallback
        elif state == 'ready':
            try:
                # Assuming the resource's read function is implicitly used
                # or passed somehow to the children
                resolved_data = resource_state.peek_data() # Hypothetical method
                return children(resolved_data) if callable(children) else children
            except Exception as e:
                # Handle errors during the rendering of children with resolved data
                console.error(f"Error rendering Suspense children: {e}")
                # Optionally render fallback or re-throw to ErrorBoundary
                return fallback() if callable(fallback) else fallback
        else:
            return None # Or some default state

    return render_suspense


class _PortalImpl:
    def __init__(self, container, children):
        self.container_selector = container
        self.children = children
        self.portal_root_node = None
        self.target_container = None
        self._mount_effect_running = False
        self.render_effect = None

    def _find_container(self):
        if self.target_container:
            return True
        if isinstance(self.container_selector, str):
            self.target_container = document.querySelector(self.container_selector)
            if not self.target_container:
                console.error(f"Portal container '{self.container_selector}' not found.")
                return False
        # Check if it looks like a DOM element
        elif hasattr(self.container_selector, 'appendChild') and hasattr(self.container_selector, 'nodeType'):
             self.target_container = self.container_selector
             return True
        else:
            console.error("Portal container must be a CSS selector string or a DOM element.")
            return False
        return True

    def mount(self):
        # Prevent re-entry and mounting if container not found
        if not self._find_container() or self._mount_effect_running:
            return

        self._mount_effect_running = True
        try:
            # Create a root DOMNode for the portal content if it doesn't exist
            if not self.portal_root_node:
                # Use a simple div as the root within the portal target
                self.portal_root_node = t.div({'aria-label': 'portal-content', 'style': {'display': 'contents'}}, [])
                self.target_container.appendChild(self.portal_root_node.element)

            # Render children into the portal root's element
            def render_portal_children():
                # Track the children source
                content = track(self.children) if callable(self.children) else self.children
                # Use DOMNode's internal mechanisms to update children
                # Check if _process_children exists and is callable
                if hasattr(self.portal_root_node, '_process_children') and callable(self.portal_root_node._process_children):
                    self.portal_root_node._process_children(content)
                else:
                    # Fallback or manual management if _process_children is not available
                    self.portal_root_node.element.innerHTML = ""
                    self._append_portal_child(content)

            # Create an effect specifically for rendering portal children
            if not self.render_effect:
                self.render_effect = create_effect(render_portal_children)

                # Register cleanup for the render effect within
                parent_effect = get_current_effect()
                if parent_effect and self.render_effect:
                    # Ensure disposal happens when the component using Portal unmounts
                    _effects[parent_effect]["disposals"].append(self.unmount) 

        finally:
            self._mount_effect_running = False


    def _append_portal_child(self, child):
        if isinstance(child, DOMNode):
            self.portal_root_node.element.appendChild(child.element)
            # Manually trigger mounts if needed
            if hasattr(child, 'mounted') and not child.mounted:
                child.mounted = True
                current_effect = self.render_effect
                if current_effect: current_effect.run_mounts()
        elif isinstance(child, list):
             for item in child: self._append_portal_child(item)
        elif child is not None:
             self.portal_root_node.element.appendChild(document.createTextNode(str(child)))

    def unmount(self):
        if self.render_effect:
            self.render_effect.dispose()
            self.render_effect = None

        if self.portal_root_node:
            self.portal_root_node.remove()

        self.portal_root_node = None
        self.target_container = None
        self._mount_effect_running = False

def Portal(container, children):
    """
    Portal component to render children into a different DOM node.
    """
    impl = _PortalImpl(container, children)
    impl.mount()
    return None


class _ErrorBoundaryImpl:
    def __init__(self, fallback, children):
        self.has_error_signal, self.set_has_error = create_signal(False)
        self.error_signal, self.set_error = create_signal(None)
        self.fallback = fallback
        self.children = children

    def _component_did_catch(self, error):
        console.error("ErrorBoundary caught an error:", error)
        # Defer the update to ensure the current render effect finishes
        from js import setTimeout
        from pyodide.ffi import create_proxy
        
        def update_state():
            batch_updates(lambda: [
                self.set_error(error),
                self.set_has_error(True)
            ])
            
        setTimeout(create_proxy(update_state), 0)

    def reset_error(self):
        """Function to allow resetting the error state, e.g., via a button in the fallback."""
        batch_updates(lambda: [
            self.set_error(None),
            self.set_has_error(False)
        ])

    def _wrap_children(self, children):
        if isinstance(children, list):
            return [self._wrap_children(child) for child in children]
            
        if callable(children) and not isinstance(children, Signal) and not isinstance(children, DOMNode):
            def wrapped_child(*args, **kwargs):
                try:
                    return children(*args, **kwargs)
                except Exception as e:
                    self._component_did_catch(e)
                    # Return a placeholder or None, the error boundary will re-render with fallback
                    return None
            return wrapped_child
            
        return children

    def render(self):
        # Track the error state signal
        is_error = track(self.has_error_signal)
        console.log(f"ErrorBoundary render. has_error: {is_error}")
        
        if is_error:
            error = self.error_signal()
            console.log(f"Rendering fallback with error: {error}")
            try:
                # Try to determine if fallback accepts 2 arguments (error, reset)
                accepts_two_args = False
                try:
                    sig = inspect.signature(self.fallback)
                    if len(sig.parameters) >= 2:
                        accepts_two_args = True
                except:
                    # If inspection fails, we can try calling with 2 args and catch TypeError
                    # But safer to assume 1 arg if we can't inspect, or try/except the call
                    pass

                if accepts_two_args:
                    return self.fallback(error, self.reset_error)
                else:
                    # Try calling with 2 args first if we couldn't inspect, just in case
                    try:
                         return self.fallback(error, self.reset_error)
                    except TypeError:
                         return self.fallback(error)
            except Exception as fb_error:
                 console.error("Error rendering ErrorBoundary fallback:", fb_error)
                 return t.div({"style": {"color": "red"}}, "Error in fallback rendering.")
        else:
            try:
                result = track(self.children) if callable(self.children) else self.children
                return self._wrap_children(result)
            except Exception as e:
                 self._component_did_catch(e)
                 # If we catch here, we need to return something or the effect will finish with None
                 # and wait for the signal update to trigger re-render
                 return None

                 try:
                    import inspect
                    try:
                        sig = inspect.signature(self.fallback)
                        if len(sig.parameters) >= 2:
                            return self.fallback(e, self.reset_error)
                        else:
                            return self.fallback(e)
                    except (ValueError, TypeError):
                        return self.fallback(e)

                 except Exception as fb_error:
                    console.error("Error rendering ErrorBoundary fallback after direct catch:", fb_error)
                    return t.div({"style": {"color": "red"}}, "Error in fallback rendering.")

def ErrorBoundary(fallback, children):
    """
    ErrorBoundary component to catch errors in children.
    """
    return _ErrorBoundaryImpl(fallback, children).render