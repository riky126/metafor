# Quick Guide

Welcome to the Metafor documentation! This page will give you an introduction to 80% of the Metafor concepts that you will use on a daily basis.

<div class="learn-box">
**You will learn**
- How to create and nest components
- How to add markup and styles
- How to display data
- How to render conditions and lists
- How to respond to events and update the screen
- How to share data between components
</div>

## Creating and nesting components

Metafor apps are made out of components. A component is a piece of the UI (user interface) that has its own logic and appearance. A component can be as small as a button, or as large as an entire page.

Metafor components are Python functions that return markup:

<div class="feature-code" data-filename="MyButton.ptml">

```python
@component("MyButton") @props {
    pass
}

@ptml {
    <button>I'm a button</button>
}
```

</div>

Now that you've declared `MyButton`, you can nest it in another component:

<div class="feature-code" data-filename="MyApp.ptml">

```python
@component("MyApp") @props {
    pass
}

@ptml {
    <div>
        <h1>Welcome to my app</h1>
        <MyButton />
    </div>
}
```

</div>

Notice that `<MyButton />` starts with a capital letter. That's how you know it's a Metafor component. Metafor component names must always start with a capital letter, while HTML tags must be lowercase.

## Writing markup with PTML

The markup syntax you've seen is called PTML (Python Template Markup Language). It is the standard way to write templates in Metafor. All of the tools we recommend for local development support PTML out of the box.

PTML is similar to HTML but integrated with Python. You have to close tags like `<br />`. Your component also can't return multiple PTML tags unless you wrap them in a shared parent:

<div class="feature-code" data-filename="AboutPage.ptml">

```python
@component("AboutPage") @props {
    pass
}

@ptml {
    <div>
        <h1>About</h1>
        <p>Hello there.<br />How do you do?</p>
    </div>
}
```

</div>

## Adding styles

In Metafor, you specify a CSS class with `className`. It works the same way as the HTML `class` attribute:

<div class="feature-code" data-filename="Avatar.ptml">

```python
@component("Avatar") @props {
    pass
}

@ptml {
    <img 
        className="avatar"
        src="https://i.imgur.com/1bX5QH6.jpg"
        alt="Gregorio Y. Zara"
    />
}
```

</div>

Then you write the CSS rules for it in a separate CSS file:

<div class="feature-code" data-filename="styles.css">

```css
.avatar {
    border-radius: 50%;
    width: 90px;
    height: 90px;
}
```

</div>

Metafor doesn't prescribe how you add CSS files. In the simplest case, you'll add a `<link>` tag in your HTML. If you use a build tool or a framework, consult its documentation to learn how to add a CSS file to your project.

## Displaying data

PTML lets you put markup into Python. You can use curly braces `@{ }` to "escape back" into Python so that you can embed some variable from your code and display it to the user. For example, this will display `user.name`:

<div class="feature-code" data-filename="Welcome.ptml">

```python
@component("Welcome") @props {
    from metafor.core import create_signal
    
    user = create_signal({"name": "Sara"})
}

@ptml {
    <h1>
        Welcome, @{user()['name']}!
    </h1>
}
```

</div>

You can also "escape into Python" from PTML attributes, but you have to use curly braces instead of quotes:

<div class="feature-code" data-filename="Avatar.ptml">

```python
@component("Avatar") @props {
    pass
}

@ptml {
    <img 
        className="avatar"
        src=@{props.get('user', {}).get('imageUrl', '')}
        alt=@{props.get('user', {}).get('name', 'User')}
    />
}
```

</div>

## Conditional rendering

In Metafor, there is no special syntax for writing conditions. Instead, you'll use the same Python techniques you use when writing regular code. For example, you can use an `if` statement to conditionally include JSX:

<div class="feature-code" data-filename="Item.ptml">

```python
@component("Item") @props {
    from metafor.components import Show
    
    @prop name: str = ""
    @prop isPacked: bool = False
}

@ptml {
    <li className="item">
        <Show when=@{lambda: props['isPacked']}
              fallback=@{lambda: <span>@{props['name']}</span>}>
            <del>@{props['name']}</del>
        </Show>
    </li>
}
```

</div>

You can also use the `@if` syntax for cleaner conditionals:

<div class="feature-code" data-filename="LoginStatus.ptml">

```python
@if success {
    <p style="color: green;">Login successful!</p>
}
```

</div>

## Rendering lists

You rely on Python features like `for` loops and the `For` component to render lists of components.

For example, let's say you have an array of products:

<div class="feature-code" data-filename="ShoppingList.ptml">

```python
@component("ShoppingList") @props {
    from metafor.components import For
    
    products = [
        {"title": "Cabbage", "id": 1},
        {"title": "Garlic", "id": 2},
        {"title": "Apple", "id": 3},
    ]
}

@ptml {
    <ul>
        <For each=@{products}>
            @{lambda product: <li key=@{product['id']}>@{product['title']}</li>}
        </For>
    </ul>
}
```

</div>

Alternatively, you can use the `@foreach` syntax which handles keys and fallbacks elegantly:

<div class="feature-code" data-filename="TodoList.ptml">

```python
@foreach todo in todos, key=lambda todo, _: todo['id'] {
    <li key=@{str(todo["id"])}>
        <input type="checkbox" />
        <span>@{todo["text"]}</span>
    </li>
}
```

</div>

## Responding to events

You can respond to events by declaring event handler functions inside your components:

<div class="feature-code" data-filename="MyButton.ptml">

```python
@component("MyButton") @props {
    from metafor.core import create_signal
    
    count, set_count = create_signal(0)
    
    def handle_click(e):
        set_count(count() + 1)
        print(f"Clicked {count()} times")
}

@ptml {
    <button onclick=@{handle_click}>
        Clicked @{count()} times
    </button>
}
```

</div>

## Updating the screen

Often, you'll want your component to "remember" some information and display it. For example, maybe you want to count the number of times a button is clicked. To do this, add state to your component.

First, import `create_signal` from `metafor.core`:

<div class="feature-code no-filename" >

```python
from metafor.core import create_signal
```

</div>

Then call it inside your component to declare a state variable:

<div class="feature-code no-filename">

```python
count, set_count = create_signal(0)
```

</div>

`create_signal` returns a pair of values: the current state (the signal) and the function to update it. You can give them any names, but the convention is `[something, set_something]`.

The first time the button is displayed, `count` will be `0` because you passed `0` to `create_signal`. When you want to change state, call `set_count()` and pass the new value to it. This will re-render the component with the new `count` value:

<div class="feature-code" data-filename="MyApp.ptml">

```python
@component("MyApp") @props {
    from metafor.core import create_signal
    
    count, set_count = create_signal(0)
    
    def handle_click(e):
        set_count(count() + 1)
}

@ptml {
    <div>
        <button onclick=@{handle_click}>
            Clicked @{count()} times
        </button>
    </div>
}
```

</div>

## Using Hooks

Functions starting with `use` are called Hooks. `create_signal` is a built-in Hook provided by Metafor.  You can also write your own Hooks to reuse stateful behavior between different components.

Hooks are more restrictive than regular functions. You can only call Hooks at the top level of your components (or other Hooks). If you want to use `create_signal` conditionally or in a loop, extract a new component and put it there.

You can find other built-in Hooks in the [Metafor API reference](api-reference.md).
