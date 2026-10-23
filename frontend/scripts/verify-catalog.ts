import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {inventory, defaultProfile, productMeta, skuCatalog} from '../src/catalog.ts';
import {initialOffers, buyerRatings, sellerAnalysis, finalOffer, buyerDecision, buyerContext} from '../src/negotiation.ts';

const exactKeys = (value:object, expected:string[]) => assert.deepEqual(Object.keys(value).sort(), [...expected].sort());
const inventoryKeys = ['sku','name','category','color','material','size','price','stock','image'];
const bundleKeys = ['id','skus','images','items_total','price'];
const ratingKeys = ['id','probability','reason'];
const profile = {...defaultProfile, styles:['Casual','Athletic'], looks:['l1','l2','l3']};
const rules = {maxItems:4, maxDiscount:15};

assert.ok(inventory.length>=61,'Seller inventory retains the original size-specific SKUs');
assert.equal(new Set(inventory.map(item=>item.sku)).size,inventory.length,'Inventory SKU IDs must be unique');
assert.equal(skuCatalog.length,inventory.length);
for (const item of inventory) {
 exactKeys(item,inventoryKeys);
 assert.ok(!/[\\/]/.test(item.image),'Wire images must be file names');
 assert.ok(existsSync(new URL('../public/images/'+item.image,import.meta.url)),`Missing image ${item.image}`);
 assert.ok(Object.values(productMeta).some(meta=>meta.skus.includes(item.sku)),`Missing metadata for ${item.sku}`);
}

const context=buyerContext(profile);
assert.deepEqual(context.sizes,{top:'M',bottom:'M'});
assert.deepEqual(context.notes,[]);
assert.equal(context.budget,200);

const initial=initialOffers(profile,rules);
assert.equal(initial.check.valid,true,initial.check.errors.join('\n'));
assert.equal(initial.payload.bundles.length,5);
assert.equal(new Set(initial.payload.bundles.map(bundle=>[...bundle.skus].sort().join('|'))).size,5);
for (const bundle of initial.payload.bundles) {
 exactKeys(bundle,bundleKeys);
 bundle.skus.forEach((sku,index)=>{
  const item=inventory.find(item=>item.sku===sku)!;
  assert.ok(item.stock>0);
  assert.equal(item.size,'M','Happy-path clothing must use the requested M SKU');
  assert.equal(bundle.images[index],item.image);
 });
}

const ratings=buyerRatings(initial.bundles);
exactKeys(ratings,['ratings']);
assert.equal(ratings.ratings.length,5);
for (const rating of ratings.ratings) {
 exactKeys(rating,ratingKeys);
 assert.ok(rating.probability>=0&&rating.probability<=1);
 assert.ok(initial.payload.bundles.some(bundle=>bundle.id===rating.id));
 assert.ok(rating.reason.length>0);
}

const analysis=sellerAnalysis(initial.bundles,ratings);
exactKeys(analysis,['avg','attribute_avgs','item_checks','works','fails','keep_skus','drop_skus','main_issue']);
const computedMean=ratings.ratings.reduce((sum,rating)=>sum+rating.probability,0)/5;
assert.ok(Math.abs(analysis.avg-computedMean)<1e-12,'Analysis average must be computed from actual ratings');
for (const [color,average] of Object.entries(analysis.attribute_avgs.color)) {
 const containing=initial.bundles.filter(bundle=>bundle.skus.some(sku=>inventory.find(item=>item.sku===sku)!.color===color));
 const expected=containing.reduce((sum,bundle)=>sum+ratings.ratings.find(rating=>rating.id===bundle.id)!.probability,0)/containing.length;
 assert.ok(Math.abs(average-expected)<1e-12,`Color average must be computed from bundles containing ${color}`);
}

const final=finalOffer(profile,rules,initial.bundles,ratings,analysis);
assert.equal(final.check.valid,true,final.check.errors.join('\n'));
exactKeys(final.payload,['final']);
exactKeys(final.payload.final,[...bundleKeys,'savings','why']);
assert.equal(final.payload.final.id,'final');
assert.equal(final.payload.final.price,149);
assert.equal(final.payload.final.savings,final.payload.final.items_total-final.payload.final.price);
for (const sku of final.payload.final.skus) {
 assert.ok(analysis.keep_skus.includes(sku),'Final offer must use retained SKUs');
 assert.ok(!analysis.drop_skus.includes(sku),'Final offer must exclude dropped SKUs');
 assert.equal(inventory.find(item=>item.sku===sku)!.size,'M');
}

const decision=buyerDecision(final.bundle,true);
exactKeys(decision,['decision','probability','reason']);
assert.equal(decision.decision,'accept');
assert.ok(decision.probability>=0&&decision.probability<=1);
assert.ok(decision.reason.length>0);

console.log(`Happy-path contract smoke passed: ${inventory.length} inventory SKUs, five valid offers, ratings, analysis, one valid $${final.payload.final.price} final offer, and accept decision.`);

