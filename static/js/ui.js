/* ==========================================================================
  VEHICLE VAULT - MASTER JAVASCRIPT
   Premium UI Interactions & Animations
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  
  // 1. Dynamic Sticky Navbar Effect
  const navbar = document.querySelector('.main-header');
  if (navbar) {
    // Add a transition in JS so the shrink effect is smooth, not sudden
    navbar.style.transition = 'padding 0.3s ease, box-shadow 0.3s ease';
    window.addEventListener('scroll', () => {
      if (window.scrollY > 20) {
        navbar.style.boxShadow = '0 10px 30px rgba(0, 0, 0, 0.08)';
        navbar.style.padding = '5px 0'; 
      } else {
        navbar.style.boxShadow = '0 4px 20px rgba(0, 0, 0, 0.03)';
        navbar.style.padding = '10px 0'; 
      }
    });
  }

  // 2. Premium Scroll Animations (Intersection Observer)
  const observerOptions = {
    root: null,
    rootMargin: '0px 0px -50px 0px', 
    threshold: 0.1
  };

  const observer = new IntersectionObserver((entries, observer) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        // FIXED: Changed 'in' to 'active' to match your CSS
        entry.target.classList.add('active'); 
        observer.unobserve(entry.target); 
      }
    });
  }, observerOptions);

  // Target all premium components
  const animatedElements = document.querySelectorAll('.modern-card, .category-card, .contact-card, .cv-card, .legal-content-card, .reveal');
  animatedElements.forEach(el => {
    el.classList.add('reveal'); 
    observer.observe(el);
  });

  // 3. Custom Dropdown Logic
  const customDropdowns = document.querySelectorAll('.cv-dropdown, .cv-user-dropdown');
  customDropdowns.forEach(dropdown => {
    dropdown.addEventListener('mouseenter', () => dropdown.classList.add('open'));
    dropdown.addEventListener('mouseleave', () => dropdown.classList.remove('open'));
  });

  // 4. Active Link Highlight
  const links = document.querySelectorAll('.navbar-nav .nav-link');
  const path = location.pathname.replace(/\/$/, '');
  links.forEach(a => {
    const href = a.getAttribute('href') || '';
    if (href === path || href === path + '/') {
      a.classList.add('active');
    }
  });

  // 5. File Upload UI Enhancer
  const fileInputs = document.querySelectorAll('input[type="file"]');
  fileInputs.forEach(input => {
    input.addEventListener('change', function(e) {
      const fileCount = e.target.files.length;
      const helperText = this.previousElementSibling; 
      
      if (helperText && helperText.tagName === 'SMALL') {
        if (fileCount > 0) {
          helperText.innerHTML = `<i class="fa-solid fa-check-circle me-1"></i> ${fileCount} image(s) securely attached and ready for upload.`;
          helperText.style.color = '#e11d48'; 
          helperText.style.fontWeight = '700';
        } else {
          helperText.innerHTML = 'Hold Ctrl/Cmd to select multiple images at once.';
          helperText.style.color = ''; 
          helperText.style.fontWeight = '';
        }
      }
    });
  });

  // 6. Button ripple effect
  document.addEventListener('click', function(e){
    const btn = e.target.closest('.btn, .btn-activity');
    if(!btn) return;
    
    // Ensure button has relative positioning for the ripple to stay inside
    if (window.getComputedStyle(btn).position === 'static') {
      btn.style.position = 'relative';
    }
    // Ensure overflow is hidden so ripple doesn't bleed out of button edges
    btn.style.overflow = 'hidden';

    const r = document.createElement('span');
    r.className = 'cv-ripple';
    const rect = btn.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    r.style.width = r.style.height = size + 'px';
    r.style.left = (e.clientX - rect.left - size/2) + 'px';
    r.style.top = (e.clientY - rect.top - size/2) + 'px';
    btn.appendChild(r);
    setTimeout(()=>{r.remove();}, 500);
  }, false);

});