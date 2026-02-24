document.addEventListener('DOMContentLoaded', function() {
  
  // 1. Dropdown Logic (Keep as is for future dropdowns)
  const dropdowns = document.querySelectorAll('.cv-dropdown, .cv-user-dropdown');
  dropdowns.forEach(function(t) {
    t.addEventListener('mouseenter', () => t.classList.add('open'));
    t.addEventListener('mouseleave', () => t.classList.remove('open'));
  });

  // 2. Active Link Fallback (Django handles this, but good to keep for pure frontend testing)
  const links = document.querySelectorAll('.nav-links a');
  const path = location.pathname.replace(/\/$/, '');
  links.forEach(function(a) {
    const href = a.getAttribute('href') || '';
    if (href === path || href === path + '/') {
      a.classList.add('active');
    }
  });

  // 3. Intersection Observer for Scroll Animations
  const observer = new IntersectionObserver(function(entries) {
    entries.forEach(function(e) {
      if (e.isIntersecting) {
        e.target.classList.add('in');
        observer.unobserve(e.target);
      }
    });
  }, { threshold: 0.1 });

  // Add the reveal class to cards and observe them
  document.querySelectorAll('.cs-card, .cv-card, .cs-feature, .cs-sell-card, .feature-card').forEach(function(el) {
    el.classList.add('reveal');
    observer.observe(el);
  });

  // 4. Mobile Menu Toggle Logic
  const mobileBtn = document.querySelector('.mobile-menu-toggle');
  const navLinks = document.querySelector('.nav-links');

  if (mobileBtn && navLinks) {
    mobileBtn.addEventListener('click', function() {
      // Toggles the menu open/closed on mobile
      navLinks.classList.toggle('mobile-open');
    });

    // Close the mobile menu if a link is clicked
    navLinks.querySelectorAll('a').forEach(function(a) {
      a.addEventListener('click', function() {
        navLinks.classList.remove('mobile-open');
      });
    });
  }
});