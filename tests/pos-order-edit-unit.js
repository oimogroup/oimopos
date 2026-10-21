/* Run with the current app.js source in a JavaScript runtime. */
function runPosOrderEditTests(source) {
  const passed = [];
  const assert = (condition, name) => {
    if (!condition) throw new Error(name);
    passed.push(name);
  };
  const section = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
  const elements = {};
  const $ = selector => elements[selector] ||= { value:'', classList:{ contains:()=>true }, title:'' };
  const products = [{id:'one', name:'Dish', price:10, available:3, unit:'portions', availableLots:[{id:'current', available:3}] }];
  const cart = new Map();
  const notices = [];
  const api = new Function('products','cart','posState','$','showToast','posCompanySettings','configureOrderSettings','closeDrawer','window','renderWorkspace','renderCart', `
    let currentOpenOrderId = null, currentCustomer = null;
    ${section('function cartItemAvailabilityIssue(', 'function renderCart(')}
    ${section('function updateQuantity(', 'function roundCashOptions(')}
    ${section('async function loadOpenOrder(', 'async function deleteOpenOrder(')}
    return {loadOpenOrder, updateQuantity, cartAvailabilityIssue, getCart:()=>cart, getOrder:()=>currentOpenOrderId};
  `)(products, cart, {customers:[],openOrders:[{id:'order', items:[
    {id:'one', name:'Dish', lotId:'gone', quantity:5}, {id:'deleted',name:'Deleted dish',quantity:2}
  ]}]}, $, message=>notices.push(message), ()=>({orders:{defaultType:'dine-in'},general:{serviceDefault:false}}), ()=>{}, ()=>{}, {}, ()=>{}, ()=>{});
  api.loadOpenOrder('order');
  assert(api.getOrder()==='order' && api.getCart().size===2, 'unavailable-order-opens-with-all-items');
  assert(api.getCart().get('one::gone').lotId==='gone', 'missing-lot-not-silently-reallocated');
  assert(api.getCart().get('deleted').name==='Deleted dish', 'deleted-item-keeps-saved-name');
  assert(Boolean(api.cartAvailabilityIssue()), 'unavailable-order-blocks-payment');
  api.updateQuantity('one::gone', -1);
  assert(api.getCart().get('one::gone').quantity===4, 'quantity-can-decrease-while-above-stock');
  api.getCart().clear();
  api.getCart().set('one::current',{...products[0],lotId:'current',quantity:3});
  assert(!api.cartAvailabilityIssue(), 'valid-order-can-be-paid');
  products[0].availableLots[0].available=2;
  assert(Boolean(api.cartAvailabilityIssue()), 'changed-lot-stock-blocks-payment');
  api.updateQuantity('one::current',-1);
  assert(!api.cartAvailabilityIssue(), 'correcting-quantity-unblocks-payment');
  return passed;
}
