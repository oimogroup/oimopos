// Run with Node: node tests/catalog-save-unit.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../admin.js'), 'utf8');

async function main() {
  const button = {disabled: false, innerHTML: 'Сохранить'};
  const originallyDisabled = {disabled: true};
  const status = {hidden: true, textContent: ''};
  const attributes = {};
  let hidden = false;
  const modal = {
    querySelectorAll: () => [button, originallyDisabled],
    setAttribute: (key, value) => { attributes[key] = value; },
    removeAttribute: key => { delete attributes[key]; },
    classList: {contains: () => hidden},
  };
  const document = {getElementById: id => ({recipeModal: modal, saveRecipeButton: button, recipeSaveStatus: status})[id]};
  const busy = new Set();
  const messages = [];
  const code = source.slice(source.indexOf('function applyWorkspacePatch('), source.indexOf('let workspaceRefreshInFlight'));
  const {withCatalogSave, applyWorkspacePatch} = new Function(
    'document', 'CatalogCover', 'catalogSavesInProgress', 'showToast', 'console',
    `${code}; return {withCatalogSave, applyWorkspacePatch};`,
  )(document, {ready: () => true}, busy, message => messages.push(message), {error() {}});

  let release, saves = 0;
  const gate = new Promise(resolve => { release = resolve; });
  const pending = withCatalogSave('recipe', async () => { saves++; await gate; hidden = true; });
  assert.equal(button.disabled, true);
  assert.equal(attributes['aria-busy'], 'true');
  assert.match(button.innerHTML, /Сохраняем/);
  assert.equal(status.hidden, false);
  await withCatalogSave('recipe', () => { throw new Error('Duplicate save'); });
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(saves, 1);
  release();
  await pending;
  assert.equal(button.disabled, false);
  assert.equal(originallyDisabled.disabled, true);
  assert.equal(button.innerHTML, 'Сохранить');
  assert.equal(busy.size, 0);
  assert.equal(attributes['aria-busy'], undefined);

  hidden = false;
  await withCatalogSave('recipe', async () => { throw new Error('Form failed'); });
  assert.equal(button.disabled, false);
  assert.equal(busy.size, 0);
  assert.ok(messages.length);

  const photo = 'unchanged-photo';
  const state = {recipes: [{id: 1, image: photo}, {id: 2, name: 'Before'}], obsolete: true};
  const updated = applyWorkspacePatch(state, {
    replace: {serviceMode: 'canteen'}, remove: ['obsolete'],
    collections: {recipes: {upsert: [{id: 2, name: 'After'}, {id: 3}], order: ['3', '1', '2']}},
  });
  assert.deepEqual(updated.recipes.map(row => row.id), [3, 1, 2]);
  assert.equal(updated.recipes[1].image, photo);
  assert.equal(updated.recipes[2].name, 'After');
  assert.equal(updated.obsolete, undefined);

  let writes = 0;
  const confirmed = {version: 8, state: {}};
  const actionCode = source.slice(source.indexOf('async function runServerAction('), source.indexOf('function applyWorkspacePatch('));
  const run = new Function('window', 'hydrateServerWorkspace', 'renderAll', 'showToast',
    'catalogSavesInProgress', 'setCatalogSaveStatus', 'serverWorkspaceState', 'console',
    `${actionCode}; return runServerAction;`)(
    {AshkanaApi: {action: async () => { writes++; return confirmed; }}},
    () => {}, () => { throw new Error('Rendering failed'); }, message => messages.push(message),
    new Set(), () => {}, {}, {error() {}},
  );
  const response = await run('recipe.upsert', {});
  assert.equal(writes, 1);
  assert.equal(response.refreshFailed, true);
  assert.match(messages.at(-1), /Изменения сохранены/);
  let reads = 0, hydrated;
  const compactResponse = {version: 8, baseVersion: 7, statePatch: {}};
  const fallback = new Function('window', 'hydrateServerWorkspace', 'renderAll', 'showToast',
    'catalogSavesInProgress', 'setCatalogSaveStatus', 'serverWorkspaceState', 'workspaceVersion', 'console',
    `${actionCode}; return runServerAction;`)(
    {AshkanaApi: {
      action: async () => compactResponse,
      workspace: async () => { reads++; return {version: 9, state: {recipes: []}}; },
    }},
    response => { hydrated = response; }, () => {}, message => messages.push(message),
    new Set(), () => {}, {}, 6, {error() {}},
  );
  await fallback('recipe.upsert', {});
  assert.equal(reads, 1);
  assert.equal(hydrated.version, 9);
  console.log('Catalog save: pending indicator, duplicate guard, cleanup, patch merge and confirmed-write handling passed');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
