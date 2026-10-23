import {inventory,productMeta,findProduct,looks,type Profile,type Rules,type Bundle,type Issue} from './catalog.ts';
import {validateBundlePayload,validateFinalPayload,INITIAL_BUNDLES,type InventoryItem,type BuyerContext,type WireBundle,type BundlePayload,type RatingsPayload,type Analysis,type FinalPayload,type Decision} from './contracts.ts';
import {quote,deliveryDays,shippingLabel,SHIPPING_TIERS,WINDOWS,REFUND_PCTS,type Shipping,type ReturnWindow,type RefundPct} from './pricing.ts';

export function buyerContext(profile:Profile):BuyerContext {
 const visualTags=looks.filter(look=>profile.looks.includes(look.id)).flatMap(look=>look.tags);
 const optional=(text:string)=>text.trim()||null;
 return {style:[...new Set([...profile.styles.map(style=>style.toLowerCase()),...visualTags.filter(tag=>['Minimal','Classic','Sporty','Expressive'].includes(tag)).map(tag=>tag.toLowerCase())])],colors_liked:['grey','taupe','white','oat'],colors_avoid:[],sizes:{top:profile.topSize,bottom:profile.bottomSize},budget:profile.budget,occasion:profile.occasions,notes:[],additional_notes:optional(profile.notes),needed_by:optional(profile.neededBy),delivery_days:profile.deliveryDays,returns_note:optional(profile.returnsNote),return_window:profile.returnWindow};
}
export function wireBundle(bundle:Bundle):WireBundle {return {id:bundle.id,skus:[...bundle.skus],images:[...bundle.images],items_total:bundle.items_total,price:bundle.price,shipping:bundle.shipping,delivery_days:bundle.delivery_days,return_window:bundle.return_window,refund_pct:bundle.refund_pct};}
export function skuFor(id:string,profile:Profile):string {
 const meta=productMeta[id];
 const size=meta.group==='bottom'?profile.bottomSize:meta.group==='accessory'?'OS':profile.topSize;
 const found=inventory.find(item=>meta.skus.includes(item.sku)&&item.size===size&&item.stock>0);
 if(!found)throw new Error('No available '+size+' SKU for '+id);
 return found.sku;
}

const clamp=(n:number,lo=0,hi=1)=>Math.max(lo,Math.min(hi,n));
const mean=(xs:number[])=>xs.reduce((a,b)=>a+b,0)/xs.length;
const items=(skus:string[])=>skus.map(sku=>findProduct(sku) as InventoryItem);

/** How well one piece suits this buyer: style overlap with their picks, and fit. */
function pieceFit(sku:string,profile:Profile):{style:number;fit:number} {
 const meta=Object.values(productMeta).find(m=>m.skus.includes(sku))!;
 const lookTags=looks.filter(l=>profile.looks.includes(l.id)).flatMap(l=>l.tags);
 const overlap=meta.styles.filter(s=>profile.styles.includes(s)).length;
 const lounge=meta.styles.includes('Loungewear')&&lookTags.includes('Minimal')?.1:0;
 const style=profile.styles.length?clamp(.1+.9*overlap/profile.styles.length+lounge):.6;
 const fit=meta.fit===profile.fit||meta.fit==='Adjustable'?1:lookTags.includes(meta.fit)?.8:.5;
 return {style,fit};
}

/** The buyer agent's read of one bundle at its price and terms. Scores are 0–100. */
function rate(skus:string[],price:number,days:number,window:ReturnWindow,refund:RefundPct,profile:Profile) {
 const pieces=skus.map(sku=>({sku,...pieceFit(sku,profile)}));
 const style=mean(pieces.map(p=>p.style)),fit=mean(pieces.map(p=>p.fit));
 const value=clamp(1-Math.max(0,price/profile.budget-.5)*.8);
 const delivery=days<=profile.deliveryDays?1:clamp(1-(days-profile.deliveryDays)*.15);
 const gap=WINDOWS.indexOf(window)-WINDOWS.indexOf(profile.returnWindow);
 const returns=gap>=0?.75+.25*refund/100:gap===-1?.5+.2*refund/100:.3+.1*refund/100;
 const weighted=.35*style+.15*fit+.2*value+.15*delivery+.15*returns;
 const probability=Math.round(clamp((weighted-.62)/.33,.02,.95)*100)/100;
 const dims:[Issue,number][]=[['style',style],['fit',fit],['value',value],['delivery',delivery],['returns',returns]];
 const [weakest,weakScore]=dims.reduce((a,b)=>b[1]<a[1]?b:a);
 const issue:Issue=weakScore>=.8?'none':weakest;
 const worst=pieces.reduce((a,b)=>b.style<a.style?b:a);
 const tradeoff=issue==='delivery'?`Arrives in ${days} days, later than the ${profile.deliveryDays} days you asked for.`
  :issue==='returns'?`The ${window} guarantee (${refund}% back) is shorter than the ${profile.returnWindow} you wanted.`
  :issue==='value'?`At ${price} dollars it uses most of your ${profile.budget} dollar budget.`
  :issue==='fit'?'Some cuts sit differently from the fit you prefer.'
  :issue==='style'?`${findProduct(worst.sku).name} is less aligned with your ${profile.styles.join(' + ')||'chosen'} direction.`
  :'Strong on style, timing, and returns.';
 const pct=(n:number)=>Math.round(n*100);
 return {scores:{price:pct(value),fit:pct(fit),style:pct(style),delivery:pct(delivery),returns:pct(returns)},probability,issue,tradeoff,reason:skus.map(sku=>findProduct(sku).name).join(' + ')+'. '+tradeoff};
}

function build(id:string,name:string,skus:string[],shipping:Shipping,window:ReturnWindow,refund:RefundPct,profile:Profile,rules:Rules):Bundle {
 const q=quote(items(skus),shipping,window,refund,profile.deliveryDays,rules.maxDiscount);
 const r=rate(skus,q.price,q.delivery_days,window,refund,profile);
 return {id,name,subtitle:`${shippingLabel(shipping)} · ${q.delivery_days}-day delivery · ${window}, ${refund}% back`,skus,images:skus.map(sku=>findProduct(sku).image),items_total:q.items_total,price:q.price,shipping,delivery_days:q.delivery_days,return_window:window,refund_pct:refund,quote:q,...r};
}

/** The cheapest shipping that arrives within the buyer's window (priority if none does). */
function shippingFor(skus:string[],profile:Profile):Shipping {return SHIPPING_TIERS.find(tier=>deliveryDays(items(skus),tier)<=profile.deliveryDays)??'priority'}

/** Candidate piece sets, best first. The seller favors style fit, then delivery speed when the
 * buyer is in a hurry, then margin (which funds a bigger bundle discount). */
function pieceSets(profile:Profile,rules:Rules):string[][] {
 const urgent=profile.deliveryDays<=5;
 const pool=Object.keys(productMeta).flatMap(id=>{try{return [{id,sku:skuFor(id,profile),group:productMeta[id].group}]}catch{return []}}).map(p=>{
  const item=findProduct(p.sku);const f=pieceFit(p.sku,profile);
  const speed=item.delivery_days<=profile.deliveryDays?1:clamp(1-(item.delivery_days-profile.deliveryDays)/7);
  return {...p,score:(urgent?.45:.6)*f.style+.15*f.fit+(urgent?.3:.15)*speed+.1*item.margin_pct/100};
 }).sort((a,b)=>b.score-a.score);
 const tops=pool.filter(p=>p.group==='top'),bottoms=pool.filter(p=>p.group==='bottom'),extras=pool.filter(p=>p.group!=='bottom');
 const sets:{skus:string[];score:number}[]=[];
 for(const b of bottoms)for(const t of tops){
  sets.push({skus:[t.sku,b.sku],score:(t.score+b.score)/2});
  if(rules.maxItems>=3){const extra=extras.filter(e=>e.sku!==t.sku)[sets.length%4];if(extra)sets.push({skus:[t.sku,b.sku,extra.sku],score:(t.score+b.score+extra.score)/3+.02});}
 }
 // Spread the pieces around so each bundle teaches the seller something new, and hold back a few
 // slots for exploratory sets further down the ranking so the ratings show what does not work.
 const spread=(list:{skus:string[];score:number}[])=>{const out:string[][]=[];const used:Record<string,number>={};
  for(const pass of [2,4,99])for(const s of list){
   if(out.some(o=>o.join()===s.skus.join()))continue;
   if(s.skus.some(sku=>(used[sku]??0)>=pass))continue;
   out.push(s.skus);s.skus.forEach(sku=>used[sku]=(used[sku]??0)+1);
  }
  return out;};
 const ranked=[...sets].sort((a,b)=>b.score-a.score);
 const best=spread(ranked),explore=spread(ranked.slice(Math.floor(ranked.length*.75)));
 const head=best.slice(0,7),scouts=explore.filter(s=>!head.some(h=>h.join()===s.join())).slice(0,3);
 const ordered:string[][]=[];
 for(const s of [...head,...scouts,...best,...explore])if(!ordered.some(o=>o.join()===s.join()))ordered.push(s);
 return ordered;
}

const names=['The everyday reset','A lighter kind of lounge','Soft layers, quick start','The weekend rotation','Off-duty essentials','The easy uniform','Coffee-run ready','A little more structure','Tonal and relaxed','The full lounge rotation','Move-friendly basics','The quiet staples','Warm-weather ease','The layered edit','Clean and simple','Ready when you are','The considered set','Errands to evenings','The comfort capsule','Back-pocket favorites'];

export function initialOffers(profile:Profile,rules:Rules):{bundles:Bundle[];payload:BundlePayload;context:BuyerContext;check:ReturnType<typeof validateBundlePayload>} {
 const context=buyerContext(profile);
 const bundles:Bundle[]=[];const seen=new Set<string>();
 pieceSets(profile,rules).forEach((skus,i)=>{
  const fast=shippingFor(skus,profile);
  const faster=SHIPPING_TIERS[Math.min(2,SHIPPING_TIERS.indexOf(fast)+1)];
  // Two offers per set: the buyer's own return window, and a different window + refund level,
  // so the twenty bundles cover every shipping speed, return window and refund option.
  const variants:[Shipping,ReturnWindow,RefundPct][]=[[fast,profile.returnWindow,REFUND_PCTS[i%3]],[faster,WINDOWS[(i+1)%3],REFUND_PCTS[(i+2)%3]]];
  for(let [shipping,window,refund] of variants){
   if(bundles.length>=INITIAL_BUNDLES)return;
   // Over budget: step down the guarantee before giving up on the set.
   let b=build('b'+(bundles.length+1),names[bundles.length],skus,shipping,window,refund,profile,rules);
   while(b.price>profile.budget&&(refund>30||window!=='2 weeks')){if(refund>30)refund=REFUND_PCTS[REFUND_PCTS.indexOf(refund)-1];else window=WINDOWS[WINDOWS.indexOf(window)-1];b=build(b.id,b.name,skus,shipping,window,refund,profile,rules);}
   const key=[...skus].sort().join('|')+shipping+window+refund;
   if(b.price>profile.budget||seen.has(key))continue;
   seen.add(key);bundles.push(b);
  }
 });
 const payload={bundles:bundles.map(wireBundle)};
 return {bundles,payload,context,check:validateBundlePayload(payload,context,inventory,rules.maxItems,rules.maxDiscount)};
}
export function buyerRatings(bundles:Bundle[]):RatingsPayload{return {ratings:bundles.map(bundle=>({id:bundle.id,probability:bundle.probability,reason:bundle.reason}))};}

export function sellerAnalysis(bundles:Bundle[],ratings:RatingsPayload):Analysis {
 const byId=new Map(ratings.ratings.map(rating=>[rating.id,rating]));
 const avg=ratings.ratings.reduce((sum,rating)=>sum+rating.probability,0)/ratings.ratings.length;
 const dims=['color','category','shipping','return_window','refund'] as const;
 const buckets:Record<string,Record<string,number[]>>=Object.fromEntries(dims.map(d=>[d,{}]));
 const heat:Record<string,number[]>={};
 for(const bundle of bundles){const probability=byId.get(bundle.id)!.probability;
  for(const dimension of ['color','category'] as const)for(const value of new Set(bundle.skus.map(sku=>findProduct(sku)[dimension])))(buckets[dimension][value]??=[]).push(probability);
  (buckets.shipping[bundle.shipping]??=[]).push(probability);(buckets.return_window[bundle.return_window]??=[]).push(probability);(buckets.refund[bundle.refund_pct+'%']??=[]).push(probability);
  for(const sku of bundle.skus)(heat[sku]??=[]).push(probability);
 }
 const attribute_avgs=Object.fromEntries(Object.entries(buckets).map(([dimension,values])=>[dimension,Object.fromEntries(Object.entries(values).map(([value,numbers])=>[value,numbers.reduce((a,b)=>a+b,0)/numbers.length]))])) as Analysis['attribute_avgs'];
 const skuHeat=(sku:string)=>mean(heat[sku]);
 const low=bundles.filter(bundle=>byId.get(bundle.id)!.probability<.5);
 const item_checks:Analysis['item_checks']=[];
 for(const bundle of low)for(const sku of bundle.skus){const hurts=skuHeat(sku)<avg-.05&&Math.max(...heat[sku])<.6;item_checks.push({bundle:bundle.id,sku,verdict:hurts?'hurts':'neutral',dimension:hurts?(bundle.issue==='style'?'style':'category'):'none',note:hurts?`${findProduct(sku).name} only appears in bundles rated below the round average.`:'This piece appears in other, better-rated offers.'});}
 const drop_skus=[...new Set(item_checks.filter(item=>item.verdict==='hurts').map(item=>item.sku))];
 const keep_skus=[...new Set(bundles.filter(bundle=>byId.get(bundle.id)!.probability>=.5).flatMap(bundle=>bundle.skus))].filter(sku=>!drop_skus.includes(sku));
 const fails=Object.entries(attribute_avgs.category).filter(([value,avg_prob])=>avg_prob<avg&&drop_skus.some(sku=>findProduct(sku).category===value)).map(([value,avg_prob])=>{const votes=item_checks.filter(c=>c.verdict==='hurts'&&findProduct(c.sku).category===value).length;return {type:'category',value,avg_prob,votes,confirmed:votes>0};});
 const works=(['color','shipping','return_window','refund'] as const).flatMap(type=>Object.entries(attribute_avgs[type]).filter(([,average])=>average>=Math.max(.5,avg)).map(([value,avg_prob])=>({type,value,avg_prob})));
 const issues=low.map(b=>b.issue).filter(i=>i!=='none');
 const main_issue=issues.length?[...new Set(issues)].sort((a,b)=>issues.filter(i=>i===b).length-issues.filter(i=>i===a).length)[0]:'none';
 return {avg,attribute_avgs,item_checks,works,fails,keep_skus,drop_skus,main_issue};
}

export function finalOffer(profile:Profile,rules:Rules,bundles:Bundle[],ratings:RatingsPayload,analysis:Analysis):{bundle:Bundle;payload:FinalPayload;check:ReturnType<typeof validateFinalPayload>} {
 const best=[...ratings.ratings].sort((a,b)=>b.probability-a.probability)[0];
 const original=bundles.find(bundle=>bundle.id===best.id)!;
 const skus=original.skus.filter(sku=>!analysis.drop_skus.includes(sku)&&analysis.keep_skus.includes(sku));
 if(skus.length<2)skus.push(...analysis.keep_skus.filter(sku=>!skus.includes(sku)).slice(0,2-skus.length));
 // Terms: the return window and refund level the buyer rated highest, never shorter than they asked for.
 const top=(type:'return_window'|'refund')=>Object.entries(analysis.attribute_avgs[type]).sort((a,b)=>b[1]-a[1])[0][0];
 let window=top('return_window') as ReturnWindow;
 if(WINDOWS.indexOf(window)<WINDOWS.indexOf(profile.returnWindow))window=profile.returnWindow;
 let refund=Number(top('refund').replace('%','')) as RefundPct;
 let bundle=build('final','Your everyday edit',skus,original.shipping,window,refund,profile,rules);
 while(bundle.price>profile.budget&&refund>30){refund=REFUND_PCTS[REFUND_PCTS.indexOf(refund)-1];bundle=build('final',bundle.name,skus,original.shipping,window,refund,profile,rules);}
 const why='Based on '+best.id+' ('+Math.round(best.probability*100)+'% estimated buy chance): retain the strongest pieces'+(analysis.drop_skus.length?', leave out the low-rated ones,':'')+` and ship ${bundle.shipping} (${bundle.delivery_days} days) with a ${window} guarantee at ${refund}% back.`;
 bundle={...bundle,subtitle:'Refined by Sunday Theory',reason:why,tradeoff:skus.map(sku=>findProduct(sku).name).join(' + ')+'. Your requested sizes, shaped by the twenty initial ratings.'};
 const payload={final:{...wireBundle(bundle),savings:bundle.items_total-bundle.price,why}};
 return {bundle,payload,check:validateFinalPayload(payload,buyerContext(profile),inventory,rules.maxItems,rules.maxDiscount,analysis.drop_skus)};
}
export function buyerDecision(bundle:Bundle,accept:boolean):Decision {return {decision:accept?'accept':'reject',probability:accept?bundle.probability:0,reason:accept?`Matches the requested sizes and style, arrives in ${bundle.delivery_days} days with a ${bundle.return_window} guarantee, at a ${bundle.price} dollar total within budget.`:'Buyer rejected the final offer.'};}
