<div className={lambda: f"counter theme-{theme()}"}>
    <h3>Counter Component</h3>
    <p>Count: {count}</p>
    <p>Doubled: {doubled}</p>
    <p>Test: {test}</p>
    
    <Show when={!data['loading']} fallback={<div>Loading...</div>}>
      <h1>Hi, I am {data['name']}.</h1>
    </Show>
    
    <For each={cats()}>{(cat, i) =>
      <li>
        <a target="_blank" href={`https://www.youtube.com/watch?v=${cat['id']}`}>
          {i + 1}: {cat['name']}
        </a>
      </li>
    }
    </For>
    
    <button className="btn btn-primary me-2" onclick={increment}>Increment</button>
    <button className="btn btn-secondary" onclick={decrement}>Decrement</button>
    <button className="btn btn-secondary" onclick={on_test}>Test</button>

    <hr/>

    <h3>Switch/Match Example</h3>
    <div className="btn-group mb-3">
        <button className="btn btn-outline-primary" onclick={() => set_tab('home')}>Home</button>
        <button className="btn btn-outline-primary" onclick={() => set_tab('profile')}>Profile</button>
        <button className="btn btn-outline-primary" onclick={() => set_tab('settings')}>Settings</button>
    </div>
    <div className="card p-3 mb-3 form-control">
        <Switch fallback={<div>Select a tab</div>}>
            <Match when={tab() == 'home'}>
                <div>Home Content</div>
            </Match>
            <Match when={tab() == 'profile'}>
                <div>Profile Content</div>
            </Match>
            <Match when={tab() == 'settings'}>
                <div>Settings Content</div>
            </Match>
        </Switch>
    </div>
    
    <hr/>

    <h3>Portal Example</h3>
    <p>Click the button below to toggle the modal.</p>
    <button className="btn btn-info" onclick={() => set_show_modal(!show_modal())}>
        {show_modal() ? "Close Modal" : "Open Modal"}
    </button>

    <Show when={show_modal()}>
        <Portal target="#modal-root">
             <div style={{
                position: 'fixed', 
                top: '0', 
                left: '0', 
                width: '100%',
                height: '100%',
                background: 'rgba(0,0,0,0.5)',
                display: 'flex',
                justifyContent: 'center',
                alignItems: 'center',
                zIndex: 1000
            }}>
                <div style={{
                    background: 'white', 
                    padding: '20px', 
                    borderRadius: '8px',
                    minWidth: '300px'
                }}>
                    <h4>Modal via Portal</h4>
                    <p>This content is portaled to #modal-root.</p>
                    <button className="btn btn-secondary" onclick={() => set_show_modal(False)}>Close</button>
                </div>
            </div>
        </Portal>
    </Show>

    <hr />
    <h3>ErrorBoundary Example</h3>
    <p>Click the button to trigger an error.</p>
    <ErrorBoundary fallback={(err, reset) => (
        <div className="alert alert-danger">
            <h4>Something went wrong!</h4>
            <p>{str(err)}</p>
            <button className="btn btn-danger" onclick={reset}>Try Again</button>
        </div>
    )}>
        <Show when={trigger_error()} fallback={<div>No error yet.</div>}>
            {/* This will raise ZeroDivisionError when rendered */}
            {1 / 0} 
        </Show>
    </ErrorBoundary>
    <button className="btn btn-warning mt-2" onclick={() => set_trigger_error(true)}>
        Trigger Error
    </button>

    <Demo>
        <span>Demo Component</span>
        <h2>Counter: {count} </h2>
    </Demo>
</div>
