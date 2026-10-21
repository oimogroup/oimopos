/* Run with the current admin.js source in a JavaScript runtime. */
function runSupplyDialogTests(source) {
  const passed = [];
  const assert = (condition,name) => { if(!condition)throw new Error(name); passed.push(name); };
  const start = source.indexOf('function openSupplyDetails(');
  const end = source.indexOf("\ndocument.addEventListener('click'", start);
  const rounding = source.slice(source.indexOf('function supplyMoney('), source.indexOf('function supplyDocumentAmount('));
  const supply = {id:'s',number:'S1',supplier:'Supplier',branchId:'b1',debt:.33633,paymentStatus:'unpaid',items:[]};
  const dialog = {open:true,innerHTML:'',querySelectorAll:()=>[],querySelector:selector=>selector==='form'?null:{}};
  const bank = {id:'bank',name:'Bank',type:'bank',status:'active'};
  const open = (role, accounts) => new Function('logisticsState','financeState','supplyDetails','currentRole','escapeHtml','money','supplyPaymentStatusLabel', `${rounding}\n${source.slice(start,end)}\nreturn openSupplyDetails;`)(
    {supplies:[supply]}, {accounts}, dialog, role, String, String, String
  )('s');
  open('owner',[bank]);
  assert(dialog.innerHTML.includes('max="0.34" value="0.34"'), 'rounded-debt-default-is-valid');
  assert(dialog.innerHTML.includes('<form>'), 'owner-can-pay');
  open('branch',[bank]);
  assert(!dialog.innerHTML.includes('<form>'), 'branch-user-not-offered-owner-payment');
  open('owner',[{id:'cash',name:'Cash',type:'cash',branchId:'b1',status:'active'}]);
  assert(!dialog.innerHTML.includes('<form>') && dialog.innerHTML.includes('Финансы'), 'unlinked-drawer-account-not-offered');
  return passed;
}

function runSupplyAmountTests(posSource, adminSource) {
  const passed = [];
  const assert = (condition,name) => { if(!condition)throw new Error(name); passed.push(name); };
  let quantity = '.333', price = '1.01';
  const row = {querySelector:selector=>({value:selector.includes('quantity')?quantity:price})};
  const document = {querySelectorAll:()=>[row]};
  const load = (source, end, total) => new Function('document', `${source.slice(source.indexOf('function supplyMoney('),source.indexOf(end))}\nreturn {round:supplyMoney,total:${total}};`)(document);
  const pos = load(posSource,'function updatePosSupplyTotal(', 'posSupplyTotal');
  const admin = load(adminSource,'function supplyPaymentAccounts(', 'supplyDocumentAmount');
  for (const [name, api] of [['pos',pos],['admin',admin]]) {
    assert(api.total()===.34, `${name}-fractional-quantity-total-rounded`);
    assert(api.round(1.005)===1.01, `${name}-decimal-half-rounded-up`);
    assert(api.round(.34-.3)===.04, `${name}-remaining-debt-rounded`);
  }
  return passed;
}
