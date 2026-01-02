---
hide:
  - navigation
  - toc
---

<div class="hero-section">
  <div class="hero-content">
    <img src="assets/metafor-logo.svg" alt="Metafor" class="hero-logo">
    <h1 class="hero-title">Metafor</h1>
    <p class="hero-subtitle">The framework for web and native user interfaces</p>
    <div class="hero-buttons">
      <a href="quick-start/" class="hero-btn-primary">Learn Metafor</a>
      <a href="api-reference/" class="hero-btn-secondary">API Reference</a>
    </div>
  </div>
</div>

<div class="feature-section">
  <div class="section-container">
    <div class="section-header">
      <h2 class="section-title">Create user interfaces<br>from components</h2>
      <p class="section-description">
        Metafor lets you build user interfaces out of individual pieces called components. 
        Create your own Metafor components like <code>Thumbnail</code>, <code>LikeButton</code>, and <code>Video</code>. 
        Then combine them into entire screens, pages, and apps.
      </p>
    </div>
    
    <div class="feature-grid">
      <div class="feature-code" data-filename="Video.ptml">

```python
@component("Video") @props {
    from metafor.core import create_signal
    
    @prop video: dict = {}
}

@ptml {
    <div className="video">
        <Thumbnail video=@{props['video']} />
        <a href=@{props['video'].url}>
            <h3>@{props['video'].title}</h3>
            <p>@{props['video'].description}</p>
        </a>
        <LikeButton video=@{props['video']} />
    </div>
}
```

</div>
      <div class="feature-preview">
        <div class="mock-card">
          <div class="mock-thumbnail"></div>
          <div class="mock-content">
            <div class="mock-title">My video</div>
            <div class="mock-desc">Video description</div>
          </div>
          <span class="mock-btn"></span>
        </div>
      </div>
    </div>
    
    <p class="section-footer">
      Whether you work on your own or with thousands of other developers, using Metafor feels the same. It is designed to let you seamlessly combine components written by independent people, teams, and organizations.
    </p>
  </div>
</div>

<div class="feature-section alt-bg">
  <div class="section-container">
    <div class="section-header">
      <h2 class="section-title">Write components<br>with code and markup</h2>
      <p class="section-description">
        Metafor components combine Python logic with declarative templates. This makes them easy to read and write.
      </p>
    </div>
    
    <div class="feature-grid reverse">
      <div class="feature-code" data-filename="VideoList.ptml">

```python
@component("VideoList") @props {
    from metafor.components import For, Show
    
    @prop videos: list = []
}

@ptml {
    <Show when=@{lambda: len(props['videos']) > 0}
          fallback=@{<p>No videos found</p>}>
        <div>
            <h1>Video List</h1>
            <div className="grid">
                <For each=@{props['videos']}>
                    @{lambda v: <Video video=@{v} />}
                </For>
            </div>
        </div>
    </Show>
}
```

</div>
      <div class="feature-preview">
        <div class="mock-card">
          <div class="mock-title" style="margin-bottom: 12px;">Video List</div>
          <div style="height: 40px; background: #f3f4f6; border-radius: 6px; margin-bottom: 8px;"></div>
          <div style="height: 40px; background: #f3f4f6; border-radius: 6px; margin-bottom: 8px;"></div>
          <div style="height: 40px; background: #f3f4f6; border-radius: 6px;"></div>
        </div>
      </div>
    </div>
    
    <div class="section-cta">
      <a href="quick-start/">See more examples →</a>
    </div>
  </div>
</div>

<div class="feature-section">
  <div class="section-container">
    <div class="section-header">
      <h2 class="section-title">Add interactivity<br>wherever you need it</h2>
      <p class="section-description">
        Metafor components receive data and return what should appear on the screen. 
        You can pass them new data in response to an interaction, like when the user types into an input.
        Metafor will then update the screen to match the new data.
      </p>
    </div>
    
    <div class="feature-grid">
      <div class="feature-code" data-filename="Counter.ptml">

```python
@component("Counter") @props {
    from metafor.core import create_signal
    
    count, set_count = create_signal(0)
    
    def increment(e):
        set_count(count() + 1)
}

@ptml {
    <div className="counter">
        <h2>Count: @{count}</h2>
        <button onclick=@{increment}>
            Click me
        </button>
    </div>
}
```

</div>
      <div class="feature-preview">
        <div class="mock-card" style="text-align: center; padding: 40px 20px;">
          <button class="mock-interactive-btn">Clicked 3 times</button>
        </div>
      </div>
    </div>
    
    <div class="section-cta">
      <a href="quick-start/">Add interactivity to your project →</a>
    </div>
  </div>
</div>

<div class="feature-section alt-bg">
  <div class="section-container">
    <div class="section-header">
      <h2 class="section-title">Go full-stack<br>with a framework</h2>
      <p class="section-description">
        Metafor is a library. It lets you put components together, but it doesn't prescribe 
        how to do routing and data fetching. To build an entire app with Metafor, 
        we recommend a full-stack Metafor framework.
      </p>
    </div>
    
    <div class="feature-grid reverse">
      <div class="feature-code" data-filename="routes.py">

```python
# routes.py
from metafor.router import Route, Router
from pages.dashboard import Dashboard
from pages.profile import Profile
from pages.login import Login

routes = [
    Route(MainLayout, children=[
        Route(Dashboard, page_title="Home"),
        Route(Profile, page_title="Profile"),
    ]),
    Route(Login, page_title="Login")
]

router = Router(routes, initial_route="/")
```

</div>
      <div class="feature-preview">
        <div class="mock-card">
          <div style="font-size: 24px; font-weight: 700; color: #23272f;">Hello, world!</div>
        </div>
      </div>
    </div>
    
    <div class="section-cta">
      <a href="tutorial/">Explore Metafor frameworks →</a>
    </div>
  </div>
</div>

<div class="feature-section">
  <div class="section-container">
    <div class="section-header">
      <h2 class="section-title">Use the best from<br>every platform</h2>
    </div>
    
    <div class="two-col-cards">
      <div class="info-card">
        <h3>Stay true to the web</h3>
        <p>People expect web app pages to load fast. On the server, Metafor lets you start streaming HTML while you're still fetching data, progressively filling in more content.</p>
        <div class="info-card-icons">
          <span>🌐</span>
          <span>⚡</span>
          <span>🚀</span>
        </div>
      </div>
      <div class="info-card">
        <h3>Go truly native</h3>
        <p>People expect native apps to look and feel like their platform. With Metafor, you can build native apps using Python with the same component model.</p>
        <div class="info-card-icons">
          <span>📱</span>
          <span>🍎</span>
          <span>🤖</span>
        </div>
      </div>
    </div>
    
    <div class="section-cta">
      <a href="community/">Read the Metafor story →</a>
    </div>
  </div>
</div>

<div class="feature-section">
  <div class="section-container">
    <div class="section-header">
      <h2 class="section-title">Upgrade when the<br>future is ready</h2>
      <p class="section-description">
        Metafor approaches changes with care. Every Metafor commit is tested on 
        business-critical surfaces with over a billion users.
      </p>
    </div>
    
    <div class="small-cards-grid">
      <div class="small-card">
        <h4>Additional Vulnerabilities in SSG</h4>
        <p>📄 Issue · 3d ago</p>
      </div>
      <div class="small-card">
        <h4>Vulnerability in React Server Components</h4>
        <p>📄 Issue · 5d ago</p>
      </div>
      <div class="small-card">
        <h4>Metafor Conf 2025 Recap</h4>
        <p>📝 Blog · 1w ago</p>
      </div>
      <div class="small-card">
        <h4>Metafor Compiler v1.0</h4>
        <p>📝 Blog · 2w ago</p>
      </div>
    </div>
    
    <div class="section-cta">
      <a href="community/">Read more Metafor news →</a>
    </div>
  </div>
</div>

<div class="community-section">
  <div class="section-container">
    <h2>Join a community<br>of millions</h2>
    <p>
      You're not alone. Two million developers from all over the world visit the Metafor docs every month. 
      Metafor is something that people and teams can agree on.
    </p>
    
    <div class="community-grid">
      <div class="community-img"></div>
      <div class="community-img"></div>
      <div class="community-img"></div>
      <div class="community-img"></div>
    </div>
    
    <p>
      Whether you're looking for education, learning, growth, or meeting new friends, 
      the Metafor community has something for everyone.
    </p>
  </div>
</div>
