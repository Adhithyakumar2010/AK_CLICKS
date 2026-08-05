const methods = document.querySelectorAll('.method');
const panels = document.querySelectorAll('.payment-option');
const methodInput = document.querySelector('input[name="method"]');
methods.forEach(button => button.addEventListener('click', () => {
  methods.forEach(item => item.classList.toggle('active', item === button));
  panels.forEach(panel => panel.classList.toggle('active', panel.dataset.panel === button.dataset.method));
  if (methodInput) methodInput.value = button.dataset.method;
}));

const form = document.querySelector('.payment-form');
if (form) {
  form.addEventListener('submit', (e) => {
    const submitBtn = form.querySelector('.payment-submit');
    if (submitBtn) {
      if (submitBtn.disabled) {
        e.preventDefault();
        return;
      }
      submitBtn.disabled = true;
      submitBtn.textContent = 'Processing payment…';
    }
  });
}
