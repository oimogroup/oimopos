const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const sandbox = {window: {}, document: {addEventListener() {}}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../admin-filters.js'), 'utf8'), sandbox);
const match = sandbox.window.AdminFilters.matchesFields;
const fields = [
  {key:'name',type:'text'}, {key:'status',options:[]},
  {key:'min',type:'number',get:row=>row.price},
  {key:'max',type:'number',compare:'max',get:row=>row.price},
];
const row = {name:'Блинчики с творогом',status:'active',price:125};
assert.equal(match(fields,{name:'ТВОРОГ',status:'active',min:'100',max:'125'},row),true);
assert.equal(match(fields,{min:'126'},row),false);
assert.equal(match(fields,{max:'124.99'},row),false);
assert.equal(match(fields,{min:'0',max:'0'},{...row,price:0}),true);
assert.equal(match(fields,{min:'2',max:'1'},row),false);
assert.equal(match(fields,{min:'not-a-number'},row),false);
assert.equal(match(fields,{min:'1'}, {...row,price:NaN}),false);
assert.equal(match(fields,{status:'stopped'},row),false);
assert.equal(match(fields,{name:''},row),true);
assert.equal(match(fields,{min:'124,5'},row),true);
const dates = [{key:'from',type:'date',get:r=>r.date},{key:'to',type:'date',compare:'max',get:r=>r.date}];
assert.equal(match(dates,{from:'2026-11-20',to:'2026-11-20'},{date:'2026-11-20'}),true);
assert.equal(match(dates,{from:'2026-11-20'},{date:''}),false);
assert.equal(match(dates,{to:'2026-11-19'},{date:'2026-11-20'}),false);
const conditional = [{key:'amount',type:'number',get:r=>r.amount,enabled:context=>context==='supplies'}];
assert.equal(match(conditional,{amount:'100'},{amount:50},'supplies'),false);
assert.equal(match(conditional,{amount:'100'},{amount:50},'inventories'),true);
console.log('Filter combinations, inclusive numeric/date bounds, zero, comma and invalid input: passed');
