// Fix search overlay click to close
document.addEventListener('DOMContentLoaded', function() {
  const overlay = document.querySelector('.md-search__overlay');
  const searchToggle = document.getElementById('__search');
  
  if (overlay && searchToggle) {
    overlay.addEventListener('click', function(e) {
      e.preventDefault();
      searchToggle.checked = false;
    });
  }
});


// Header scroll effect for landing page
document.addEventListener('DOMContentLoaded', function() {
  const header = document.querySelector('.md-header');
  
  if (header) {
    window.addEventListener('scroll', function() {
      if (window.scrollY > 0) {
        header.classList.add('header-scrolled');
      } else {
        header.classList.remove('header-scrolled');
      }
    });
  }
});
