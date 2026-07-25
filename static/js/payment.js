const methods = document.querySelectorAll('.method');
const panels = document.querySelectorAll('.payment-option');
const methodInput = document.querySelector('input[name="method"]');
methods.forEach(button => button.addEventListener('click', () => {
  methods.forEach(item => item.classList.toggle('active', item === button));
  panels.forEach(panel => panel.classList.toggle('active', panel.dataset.panel === button.dataset.method));
  methodInput.value = button.dataset.method;
}));
