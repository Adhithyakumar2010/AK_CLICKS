document.querySelector('.sidebar-toggle')?.addEventListener('click', () => {
  document.body.classList.toggle('sidebar-open');
});

const dashboardNav = document.querySelector('.customer-nav');
if (dashboardNav && !dashboardNav.querySelector('[data-home-link]')) {
  const homeLink = document.createElement('a');
  homeLink.href = '/';
  homeLink.dataset.homeLink = '';
  homeLink.innerHTML = '<i class="fa-solid fa-globe"></i>Return to Home';
  dashboardNav.appendChild(homeLink);
}
