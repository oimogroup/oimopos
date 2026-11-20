/* Field definitions for each registry; access checks remain in the data sources. */
function stockFilterMetrics(item) {
  const selected = document.getElementById('stockWarehouseFilter')?.value;
  const ids = currentRole === 'owner'
    ? branches.filter(branch => !selected || selected === 'all' || String(branch.id) === selected).map(branch => branch.id)
    : [currentSession.branchId];
  let quantity = 0, value = 0;
  ids.forEach(id => { const amount = branchStock(id, item.id); quantity += amount; value += amount * branchUnitCost(id, item.id); });
  return {quantity, value, cost: quantity ? value / quantity : ids.length === 1 ? branchUnitCost(ids[0], item.id) : 0};
}

function mountAdminFilters() {
  const F = window.AdminFilters;
  if (!F) return;
  const account = [currentSession.tenantId || 'local', currentSession.id || currentSession.login || currentRole, currentSession.branchId || 'all'].join(':');
  if (mountAdminFilters.account === account) return;
  F.setAccount(account);
  const number = (key, label, get, compare = 'min') => ({key, label, get, type: 'number', compare});
  const range = (key, label, get) => [number(`${key}Min`, `${label} от`, get), number(`${key}Max`, `${label} до`, get, 'max')];
  const status = {key: 'status', label: 'Состояние', options: [['active','В продаже'],['stopped','Остановлены']], get: row => (row._groupActive ?? row.is_active) === false ? 'stopped' : 'active'};
  const photo = {key: 'photo', label: 'Фотография', options: [['yes','С фото'],['no','Без фото']], get: row => row.image ? 'yes' : 'no'};
  const stations = () => stationNamesWithLegacy().map(name => [name, name]);
  const authorizedBranches = () => branches.filter(branch => currentRole === 'owner' || branch.id === currentSession.branchId).map(branch => [branch.id, branch.name]);
  const branch = {key: 'branch', label: 'Заведение', options: authorizedBranches, get: row => row.branch_id || row.branchId};
  const stockTest = (value, amount, limit) => value === 'positive' ? amount > 0 : value === 'zero' ? amount === 0 : value === 'negative' ? amount < 0 : amount <= Number(limit || 0);
  const controls = (...entries) => entries.map(entry => Array.isArray(entry) ? {id: entry[0], initial: entry[1]} : entry);
  const register = config => F.register(config);
  register({scope:'recipe-list', toolbar:'#menu-pane-recipes .table-toolbar', table:'#recipesTable', columns:6, render:renderRecipes,
    controls:controls('recipeSearch',['recipeCategory','Все категории'],['recipeStationFilter','Все цеха']),
    fields:[status, photo, ...range('price','Цена',row=>row.price), ...range('cost','Себестоимость',recipeCost),
      {key:'ingredient',label:'Ингредиент в составе',options:()=>ingredients.map(row=>[row.id,row.name]),test:(value,row)=>CatalogComposition.flatten(row,{ingredients,preparations}).some(component=>String(component.ingredientId)===value)}]});
  register({scope:'product-list',toolbar:'#menu-pane-products .table-toolbar',table:'#productsTable',columns:8,render:renderProducts,
    controls:controls('productSearch',['productCategoryFilter','Все категории']),fields:[status,photo,...range('price','Цена',row=>row.price),
      {key:'unit',label:'Единица',options:['кг','л','шт'],get:row=>row.unit},
      {key:'station',label:'Цех',options:stations,get:row=>row.station},
      {key:'stock',label:'Наличие',options:[['positive','В наличии'],['zero','Нулевой остаток'],['low','На уровне лимита и ниже']],test:(value,row)=>stockTest(value,branchStock(currentSession.branchId||pendingOwnerObjectScope||branches[0]?.id,row.id),row.limit)}]});
  register({scope:'preparation-list',toolbar:'#menu-pane-preparations .table-toolbar',table:'#preparationsTable',columns:5,render:renderPreparations,
    controls:controls('preparationSearch',['preparationCategoryFilter','Все категории']),fields:[status,photo,{key:'station',label:'Цех',options:stations,get:row=>row.station},...range('cost','Себестоимость',preparationCost)]});
  register({scope:'ingredient-list',toolbar:'.ingredient-filters',legacy:'.ingredient-filters .ux-advanced-filters',table:'#ingredientsTable',render:renderIngredientsMenu,
    controls:controls('ingredientSearch','ingredientCategoryFilter','ingredientUnitFilter','ingredientStockFilter','ingredientUsageFilter',['ingredientBranchFilter',String(currentSession.branchId||branches[0]?.id||'')]),
    fields:[...range('cost','Себестоимость',row=>row.cost),...range('quantity','Остаток',row=>row.stock)]});
  register({scope:'category-list',before:'#menuCategoriesTable',table:'#menuCategoriesTable',columns:5,render:renderMenuCategories,
    fields:[{key:'search',label:'Название категории',type:'text',get:row=>row.name},status,
      {key:'content',label:'Содержимое',options:[['both','Товары и техкарты'],['products','С товарами'],['recipes','С техкартами'],['empty','Пустые']],test:(value,row)=>{
        const p=products.some(item=>item.category===row.name),r=recipes.some(item=>item.category===row.name);
        return value==='both'?p&&r:value==='products'?p:value==='recipes'?r:!p&&!r;
      }}]});
  register({scope:'stock-list',toolbar:'#stockSearch',table:'#stockTable',columns:7,render:renderStock,
    controls:controls('stockSearch',['stockCategoryFilter','Все категории'],['stockWarehouseFilter',currentRole==='owner'?'all':String(currentSession.branchId||'')]),
    fields:[{key:'type',label:'Тип позиции',options:[['ingredient','Ингредиенты'],['product','Товары']],get:row=>isProductEntity(row)?'product':'ingredient'},
      {key:'stock',label:'Остаток',options:[['positive','В наличии'],['zero','Нулевой'],['negative','Отрицательный'],['low','На уровне лимита и ниже']],test:(value,row)=>stockTest(value,stockFilterMetrics(row).quantity,row.limit)},
      ...range('cost','Себестоимость',row=>stockFilterMetrics(row).cost),...range('value','Стоимость остатка',row=>stockFilterMetrics(row).value)]});
  register({scope:'suppliers',toolbar:'#supplierSearch',table:'#suppliersTable',columns:9,render:renderSuppliers,
    controls:controls('supplierSearch',['supplierStatusFilter','active']),fields:[{key:'debt',label:'Задолженность',options:[['yes','С долгом'],['no','Без долга']],get:row=>supplierDocuments(row).reduce((sum,doc)=>sum+Number(doc.debt||0),0)>0?'yes':'no'},
      ...range('debtAmount','Сумма долга',row=>supplierDocuments(row).reduce((sum,doc)=>sum+Number(doc.debt||0),0))]});
  register({scope:'documents',toolbar:'#documentFilters',hideReset:'resetDocumentFilters',context:()=>activeDocumentFilterTab||'supplies',render:()=>renderDocuments(activeDocumentFilterTab||'supplies'),
    controls:controls('documentSearch','documentDateFrom','documentDateTo',['documentPartyFilter','all'],['documentStatusFilter','all']),
    fields:[{key:'employee',label:'Сотрудник',type:'text',get:row=>[row.receivedBy,row.createdBy,row.shippedBy,row.responsible].filter(Boolean).join(' ')},
      {key:'comment',label:'Комментарий / причина',type:'text',get:row=>[row.comment,row.reason,row.description,row.reviewComment].filter(Boolean).join(' ')},
      {key:'category',label:'Категория позиции',options:()=>[...new Set([...ingredients,...products,...recipes].map(row=>row.category).filter(Boolean))].sort(),test:(value,row)=>(row.items||[]).some(item=>logisticsItem(item.itemId||item.ingredientId)?.category===value)},
      ...range('amount','Сумма',row=>Number(row.total??row.amount??0)).map(field=>({...field,enabled:context=>['supplies','writeoff'].includes(context)}))]});
  register({scope:'employees',toolbar:'.employee-toolbar',table:'#employeesTable',render:renderEmployees,
    controls:controls('employeeSearch',['employeeRoleFilter','all'],['employeeStatusFilter','active']),fields:[branch,{key:'pin',label:'PIN для кассы',options:[['yes','Есть PIN'],['no','Без PIN']],get:row=>row.has_pin?'yes':'no'}]});
  register({scope:'finance-operations',toolbar:'.finance-transaction-toolbar',table:'#financeTransactionsTable',columns:8,render:()=>renderFinanceTransactions(financeContext()),
    controls:controls('financeTransactionSearch',['financeTransactionTypeFilter','all'],['financeTransactionAccountFilter','all']),
    fields:[{key:'category',label:'Категория операции',options:()=>[...new Set(financeTransactionRows().map(row=>row.categoryName||financeCategory(row.categoryId)?.name||'Перевод между счетами'))].sort(),get:row=>row.categoryName||financeCategory(row.categoryId)?.name||'Перевод между счетами'},
      {key:'counterparty',label:'Контрагент / сотрудник',type:'text',get:row=>row.counterparty},...range('amount','Сумма',row=>row.amount)]});
  register({scope:'receipts',toolbar:'.receipt-toolbar',render:renderReceipts,
    controls:controls('receiptSearch',['receiptPaymentFilter','all'],['receiptCashierFilter','all'],['receiptStatusFilter','all']),
    fields:[...range('amount','Сумма чека',row=>row.total),{key:'source',label:'Источник',options:[['pos','Касса'],['external','Внешний реестр']],get:row=>isExternalSale(row)?'external':'pos'}]});
  register({scope:'abc',toolbar:'#abcSearch',render:renderABC,controls:controls('abcSearch',['abcTypeFilter','all'],['abcCategoryFilter','all']),
    fields:[...range('revenue','Выручка',row=>row.revenue),...range('profit','Прибыль',row=>row.profit)]});
  register({scope:'production-journal',before:'#productionJournalTable',table:'#productionJournalTable',columns:7,render:renderProductionJournal,
    fields:[{key:'search',label:'Номер или техкарта',type:'text',get:row=>`${row.number} ${recipes.find(item=>String(item.id)===String(row.recipeId))?.name||''}`},
      {key:'status',label:'Состояние выпуска',options:[['closed','Закрыт'],['serving','На раздаче'],['kitchen','На кухне']],get:row=>row.status==='closed'?'closed':row.transferredWeight?'serving':'kitchen'},
      {key:'dateFrom',label:'С даты',type:'date',get:row=>row.createdAt?analyticsDateValue(new Date(row.createdAt)):''},
      {key:'dateTo',label:'По дату',type:'date',compare:'max',get:row=>row.createdAt?analyticsDateValue(new Date(row.createdAt)):''}]});
  register({scope:'ingredient-categories',before:'#ingredientCategoriesTable',table:'#ingredientCategoriesTable',columns:4,render:renderMenuCategories,
    fields:[{key:'search',label:'Категория ингредиентов',type:'text',get:row=>row}]});
  register({scope:'stations',before:'#stationsTable',table:'#stationsTable',columns:5,render:renderMenuCategories,
    fields:[{key:'search',label:'Название или принтер',type:'text',get:row=>`${row.name} ${row.destination||''}`},branch]});
  register({scope:'registers',before:'#registersTable',table:'#registersTable',columns:6,render:renderRegisters,
    fields:[{key:'search',label:'Касса, логин или устройство',type:'text',get:row=>[row.name,row.account_login,row.device_label].filter(Boolean).join(' ')},branch,
      {key:'status',label:'Состояние кассы',options:[['online','В сети'],['offline','Не в сети'],['disabled','Отключена']],get:row=>!row.is_active?'disabled':row.online?'online':'offline'}]});
  register({scope:'finance-accounts',before:'#financeAccountsTable',table:'#financeAccountsTable',columns:7,render:renderFinanceAccounts,
    fields:[{key:'search',label:'Название счёта',type:'text',get:row=>row.name},branch,
      {key:'type',label:'Тип счёта',options:()=>[...new Set(financeState.accounts.map(row=>row.type))].map(type=>[type,financeAccountTypeLabel(type)]),get:row=>row.type},
      {key:'status',label:'Состояние счёта',options:[['active','Активный'],['inactive','Архивный']],get:row=>row.status==='active'?'active':'inactive'}]});
  register({scope:'finance-shifts',before:'#financeShiftsTable',table:'#financeShiftsTable',columns:9,render:()=>renderFinanceShifts(financeContext()),
    fields:[{key:'search',label:'Касса или сотрудник',type:'text',get:row=>[row.id,row.registerName,row.openedBy,row.closedBy].filter(Boolean).join(' ')},
      {key:'status',label:'Состояние смены',options:[['open','Открыта'],['closed','Закрыта']],get:row=>row.closedAt?'closed':'open'},
      {key:'variance',label:'Расхождение',options:[['yes','С расхождением'],['no','Без расхождения']],test:(value,row)=>row.variance!=null&&(value==='yes'?Number(row.variance)!==0:Number(row.variance)===0)}]});
  mountAdminFilters.account = account;
}
