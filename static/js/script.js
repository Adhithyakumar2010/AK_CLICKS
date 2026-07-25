const menuButton = document.querySelector('.menu-toggle');
const navigation = document.querySelector('.site-header nav');
if (menuButton && navigation) menuButton.addEventListener('click', () => navigation.classList.toggle('open'));

const bookingDate = document.querySelector('input[name="booking_date"]');
if (bookingDate) bookingDate.min = new Date().toISOString().split('T')[0];

const products = JSON.parse(document.getElementById('products-data')?.textContent || '[]');
let cart = JSON.parse(localStorage.getItem('akClicksCart') || '[]');
const money = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const cartButton = document.querySelector('.cart-bar');
const cartDrawer = document.querySelector('.cart-drawer');
function renderCart() {
  const list = document.querySelector('.cart-items'); const total = cart.reduce((sum, item) => sum + item.price, 0);
  if (!list) return;
  list.innerHTML = cart.length ? cart.map(item => `<div class="cart-item"><div><strong>${item.name}</strong><br><small>${money.format(item.price)}</small></div><button type="button" data-remove="${item.id}">Remove</button></div>`).join('') : '<p class="empty-cart">Your cart is waiting for a story.</p>';
  document.querySelector('.cart-total strong').textContent = money.format(total);
  document.querySelector('input[name="items"]').value = cart.map(item => item.name).join(', ');
  document.querySelector('input[name="total"]').value = total;
  if (cartButton) cartButton.textContent = `Bag (${cart.length}) · ${money.format(total)}`;
  localStorage.setItem('akClicksCart', JSON.stringify(cart));
}
document.querySelectorAll('[data-add]').forEach(button => button.addEventListener('click', () => { const product = products.find(item => item.id === button.dataset.add); if (product) { cart.push(product); renderCart(); cartDrawer.classList.add('open'); } }));
document.querySelector('.cart-close')?.addEventListener('click', () => cartDrawer.classList.remove('open'));
cartButton?.addEventListener('click', () => cartDrawer.classList.add('open'));
document.querySelector('.cart-items')?.addEventListener('click', event => { const id = event.target.dataset.remove; if (id) { cart = cart.filter(item => item.id !== id); renderCart(); } });
document.querySelector('.cart-form')?.addEventListener('submit', event => { if (!cart.length) { event.preventDefault(); alert('Please add an item to your bag first.'); } });
renderCart();
