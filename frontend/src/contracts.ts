/** Wire formats from the repository's json_formats.md. Dollars, not cents. */
export type InventoryItem = {
 sku:string; name:string; category:string; color:string; material:string;
 size:string; price:number; stock:number; image:string;
};
export type BuyerContext = {
 style:string[]; colors_liked:string[]; colors_avoid:string[];
 sizes:{top:string; bottom:string; shoe?:string}; budget:number; occasion:string; notes:string[];
};
export type WireBundle = {id:string; skus:string[]; images:string[]; items_total:number; price:number};
export type BundlePayload = {bundles:WireBundle[]};
export type Rating = {id:string; probability:number; reason:string};
export type RatingsPayload = {ratings:Rating[]};
export type Check = {stage:'bundles'|'final'; valid:boolean; errors:string[]};
export type AnalysisDimension = 'category'|'style'|'color'|'material'|'size'|'price'|'none';
export type AnalysisDocument = {
 avg:number;
 attribute_avgs:{color:Record<string,number>; category:Record<string,number>; [attribute:string]:Record<string,number>};
 item_checks:{bundle:string; sku:string; verdict:'hurts'|'neutral'|'helps'; dimension:AnalysisDimension; note:string}[];
 works:{type:string; value:string; avg_prob:number}[];
 fails:{type:string; value:string; avg_prob:number; votes:number; confirmed:boolean}[];
 keep_skus:string[]; drop_skus:string[]; main_issue:string;
};
export type FinalPayload = {final:WireBundle & {savings:number; why:string}};
export type DecisionPayload = {decision:'accept'|'reject'; probability:number; reason:string};
export type Analysis = AnalysisDocument;
export type Decision = DecisionPayload;

const object = (value:unknown):value is Record<string,unknown> => typeof value==='object' && value!==null && !Array.isArray(value);
const strings = (value:unknown):value is string[] => Array.isArray(value) && value.every(item=>typeof item==='string' && item.trim().length>0);
const number = (value:unknown):value is number => typeof value==='number' && Number.isFinite(value);
const text = (value:unknown):value is string => typeof value==='string' && value.trim().length>0;
const normalize = (value:string) => value.trim().toLowerCase();
const close = (left:number,right:number) => Math.abs(left-right)<0.005;
const filename = (value:string) => !/[\\/]/.test(value) && /^[^\s]+\.[a-z0-9]+$/i.test(value);

/** Unknown categories fail closed rather than silently bypass the size rule. */
function slot(item:InventoryItem):'top'|'bottom'|'shoe'|'one-size'|null {
 const category=normalize(item.category).replace(/[-_]/g,' ');
 if (['accessory','accessories','socks','hat','hats','belt','belts'].includes(category) && item.size==='OS') return 'one-size';
 if (['pants','pant','shorts','short','jeans','jean','trousers','trouser','joggers','jogger','leggings'].includes(category)) return 'bottom';
 if (['boots','boot','sneakers','sneaker','loafers','loafer','shoes','shoe','sandals','sandal'].includes(category)) return 'shoe';
 if (['jacket','jackets','tee','tees','t shirt','t shirts','shirt','shirts','hoodie','hoodies','sweatshirt','sweatshirts','crewneck','blazer','blazers','top','tops','sweater','sweaters','overshirt'].includes(category)) return 'top';
 return null;
}

/** Supported notes are literal demo rules, evaluated against explicit product names.
 * This is not a natural-language parser or a claim to infer unlisted attributes. */
function noteErrors(notes:string[],items:InventoryItem[]):string[] {
 const errors:string[]=[];
 for (const note of notes) {
  const rule=normalize(note);
  if (rule==='no graphic prints') {
   if (items.some(item=>/\b(graphic|printed|print)\b/i.test(item.name))) errors.push(`breaks note '${note}'`);
  } else if (rule==='no skinny fits') {
   if (items.some(item=>/\bskinny\b/i.test(item.name))) errors.push(`breaks note '${note}'`);
  } else errors.push(`unsupported strict note '${note}'; explicit validation is required`);
 }
 return errors;
}

function commonErrors(context:BuyerContext,inventory:InventoryItem[],maxItems:number,maxDiscount?:number):string[] {
 const errors:string[]=[];
 if (!Number.isInteger(maxItems)||maxItems<2||maxItems>5) errors.push('maxItems must be an integer from 2 to 5');
 if (maxDiscount!==undefined && (!number(maxDiscount)||maxDiscount<0||maxDiscount>100)) errors.push('maxDiscount must be a percentage from 0 to 100');
 if (!number(context.budget)||context.budget<=0) errors.push('buyer budget must be positive');
 if (!text(context.sizes.top)||!text(context.sizes.bottom)) errors.push('buyer top and bottom sizes are required');
 if (!strings(context.colors_avoid)||!strings(context.notes)) errors.push('colors_avoid and notes must be string arrays');
 const ids=new Set<string>();
 for (const item of inventory) {
  if (ids.has(item.sku)) errors.push(`inventory has duplicate SKU ${item.sku}`);
  ids.add(item.sku);
 }
 return errors;
}

function checkBundle(value:unknown,context:BuyerContext,inventory:InventoryItem[],maxItems:number,maxDiscount?:number):string[] {
 if (!object(value)) return ['bundle must be an object'];
 const errors:string[]=[];
 const id=text(value.id)?value.id:'bundle';
 if (!text(value.id)) errors.push('id is required');
 if (!strings(value.skus)||!strings(value.images)||!number(value.items_total)||!number(value.price)) return [`${id}: invalid bundle schema (skus, images, items_total, price)`];
 const images=value.images;
 if (value.skus.length<2||value.skus.length>Math.min(5,maxItems)) errors.push(`must contain 2–${Math.min(5,maxItems)} items`);
 if (new Set(value.skus).size!==value.skus.length) errors.push('repeated SKU');
 if (value.images.length!==value.skus.length) errors.push('images must have the same length and order as skus');
 const items:InventoryItem[]=[];
 const bySku=new Map(inventory.map(item=>[item.sku,item]));
 value.skus.forEach((sku,index)=>{
  const item=bySku.get(sku);
  if (!item) {errors.push(`unknown SKU ${sku}`);return;}
  items.push(item);
  if (!Number.isInteger(item.stock)||item.stock<=0) errors.push(`${sku} is out of stock`);
  if (!number(item.price)||item.price<=0) errors.push(`${sku} has an invalid inventory price`);
  if (!filename(item.image)||images[index]!==item.image) errors.push(`${sku}: image must be inventory filename ${item.image} in SKU order`);
  const sizeSlot=slot(item);
  if (!sizeSlot) errors.push(`${sku}: unsupported category for size validation (${item.category})`);
  else if (sizeSlot!=='one-size' && (!context.sizes[sizeSlot]||item.size!==context.sizes[sizeSlot])) errors.push(`${sku}: wrong ${sizeSlot} size (${item.size}; requested ${context.sizes[sizeSlot]||'unspecified'})`);
  const color=normalize(item.color);
  for (const avoided of context.colors_avoid) {
   const escaped=normalize(avoided).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
   if (new RegExp(`(^|\\W)${escaped}($|\\W)`,'i').test(color)) errors.push(`${sku}: avoided color '${avoided}'`);
  }
 });
 const computedTotal=items.reduce((sum,item)=>sum+item.price,0);
 if (!close(value.items_total,computedTotal)) errors.push(`items_total must equal computed inventory total ${computedTotal}`);
 if (value.price<computedTotal*.6-1e-8||value.price>computedTotal*1.05+1e-8) errors.push('price must be 60–105% of the computed item total');
 if (value.price>context.budget+1e-8) errors.push(`price exceeds buyer budget ${context.budget}`);
 if (maxDiscount!==undefined && value.price<computedTotal*(1-maxDiscount/100)-1e-8) errors.push(`discount exceeds seller maximum ${maxDiscount}%`);
 errors.push(...noteErrors(context.notes,items));
 return errors.map(error=>`${id}: ${error}`);
}

export function validateBundlePayload(payload:unknown,context:BuyerContext,inventory:InventoryItem[],maxItems=5,maxDiscount?:number):Check {
 const errors=commonErrors(context,inventory,maxItems,maxDiscount);
 if (!object(payload)||!Array.isArray(payload.bundles)) errors.push('payload must contain a bundles array');
 else {
  if (payload.bundles.length!==5) errors.push('exactly five initial bundles are required');
  const ids=new Set<string>(); const combinations=new Set<string>();
  for (const bundle of payload.bundles) {
   errors.push(...checkBundle(bundle,context,inventory,maxItems,maxDiscount));
   if (object(bundle)&&text(bundle.id)) {if(ids.has(bundle.id))errors.push(`duplicate bundle id ${bundle.id}`);ids.add(bundle.id);}
   if (object(bundle)&&strings(bundle.skus)) {
    const combination=[...bundle.skus].sort().join('|');
    if (combinations.has(combination)) errors.push('initial bundles must have different SKU combinations');
    combinations.add(combination);
   }
  }
 }
 return {stage:'bundles',valid:errors.length===0,errors};
}

export function validateFinalPayload(payload:unknown,context:BuyerContext,inventory:InventoryItem[],maxItems=5,maxDiscount?:number,dropSkus:readonly string[]=[]):Check {
 const errors=commonErrors(context,inventory,maxItems,maxDiscount);
 if (!object(payload)||!object(payload.final)||'bundles' in payload) errors.push('exactly one final bundle is required under final');
 else {
  const final=payload.final;
  errors.push(...checkBundle(final,context,inventory,maxItems,maxDiscount));
  if (!text(final.why)) errors.push('final: why is required');
  if (!number(final.savings)||!number(final.items_total)||!number(final.price)||!close(final.savings,final.items_total-final.price)) errors.push('final: savings must equal items_total minus price');
  if (strings(final.skus)) for (const sku of final.skus) if (dropSkus.includes(sku)) errors.push(`final: banned drop_skus item ${sku}`);
 }
 return {stage:'final',valid:errors.length===0,errors};
}
