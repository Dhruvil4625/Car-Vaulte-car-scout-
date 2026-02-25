/* ==========================================================================
   CAR SCOUT - MASTER JAVASCRIPT
   Premium UI Interactions & Animations
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  
  // 1. Dynamic Sticky Navbar Effect
  const navbar = document.querySelector('.main-header');
  if (navbar) {
    window.addEventListener('scroll', () => {
      if (window.scrollY > 20) {
        navbar.style.boxShadow = '0 10px 30px rgba(0, 0, 0, 0.08)';
        navbar.style.padding = '5px 0'; // Smoothly shrink padding
      } else {
        navbar.style.boxShadow = '0 4px 20px rgba(0, 0, 0, 0.03)';
        navbar.style.padding = '10px 0'; // Return to original
      }
    });
  }

  // 2. Premium Scroll Animations (Intersection Observer)
  const observerOptions = {
    root: null,
    rootMargin: '0px 0px -50px 0px', // Triggers slightly before the element comes fully into view
    threshold: 0.1
  };

  const observer = new IntersectionObserver((entries, observer) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('in');
        observer.unobserve(entry.target); // Only animate once per page load
      }
    });
  }, observerOptions);

  // Target all our new premium components
  const animatedElements = document.querySelectorAll('.modern-card, .category-card, .contact-card, .cv-card, .legal-content-card');
  animatedElements.forEach(el => {
    el.classList.add('reveal'); // Adds base hidden state
    observer.observe(el);
  });

  // 3. Custom Dropdown Logic (Fallback for non-Bootstrap dropdowns)
  const customDropdowns = document.querySelectorAll('.cv-dropdown, .cv-user-dropdown');
  customDropdowns.forEach(dropdown => {
    dropdown.addEventListener('mouseenter', () => dropdown.classList.add('open'));
    dropdown.addEventListener('mouseleave', () => dropdown.classList.remove('open'));
  });

  // 4. Active Link Highlight (Dynamic Route Matching fallback)
  const links = document.querySelectorAll('.navbar-nav .nav-link');
  const path = location.pathname.replace(/\/$/, '');
  links.forEach(a => {
    const href = a.getAttribute('href') || '';
    if (href === path || href === path + '/') {
      a.classList.add('active');
    }
  });

  // 5. File Upload UI Enhancer (For the "Sell Car" Page)
  const fileInputs = document.querySelectorAll('input[type="file"]');
  fileInputs.forEach(input => {
    input.addEventListener('change', function(e) {
      const fileCount = e.target.files.length;
      // Looks for the <small> tag right above the file input
      const helperText = this.previousElementSibling; 
      
      if (helperText && helperText.tagName === 'SMALL') {
        if (fileCount > 0) {
          helperText.innerHTML = `<i class="fa-solid fa-check-circle me-1"></i> ${fileCount} image(s) securely attached and ready for upload.`;
          helperText.style.color = '#e11d48'; // Crimson Red
          helperText.style.fontWeight = '700';
        } else {
          helperText.innerHTML = 'Hold Ctrl/Cmd to select multiple images at once.';
          helperText.style.color = ''; 
          helperText.style.fontWeight = '';
        }
      }
    });
  });

});