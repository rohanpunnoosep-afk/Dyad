import {inventory,productMeta,findProduct,looks,type Profile,type Rules,type Bundle} from './catalog.ts';
import {validateBundlePayload,validateFinalPayload,type BuyerContext,type WireBundle,type BundlePayload,type RatingsPayload,type Analysis,type FinalPayload,type Decision} from './contracts.ts';

export function buyerContext(profile:Profile):BuyerContext {
 const visualTags=looks.filter(look=>profile.looks.includes(look.id)).flatMap(look=>look.tags);
 return {style:[...new Set([...profile.styles.map(style=>style.toLowerCase()),...visualTags.filter(tag=>['Minimal','Classic','Sporty','Expressive'].includes(tag)).map(tag=>tag.toLowerCase())])],colors_liked:['grey','taupe','white','oat'],colors_avoid:[],sizes:{top:profile.topSize,bottom:profile.bottomSize},budget:profile.budget,occasion:profile.occasions,notes:[]};
}
export function wireBundle(bundle:Bundle):WireBundle {return {id:bundle.id,skus:[...bundle.skus],images:[...bundle.images],items_total:bundle.items_total,price:bundle.price};}
export function skuFor(id:string,profile:Profile):string {
 const meta=productMeta[id];
 const size=meta.group==='bottom'?profile.bottomSize:meta.group==='accessory'?'OS':profile.topSize;
 const found=inventory.find(item=>meta.skus.includes(item.sku)&&item.size===size&&item.stock>0);
 if(!found)throw new Error('No available '+size+' SKU for '+id);
 return found.sku;
}
const templates=[
 {name:'The everyday reset',subtitle:'Best initial offer',products:['p01','p02','p03'],price:149,fit:97,style:98,probability:.84,issue:'none',tradeoff:'A hoodie is a warmer layer. The tee works on its own on warmer afternoons.'},
 {name:'A lighter kind of lounge',subtitle:'A lower total',products:['p04','p05','p03'],price:129,fit:96,style:89,probability:.73,issue:'value',tradeoff:'Shorts replace full-length joggers, so there is less coverage on cool evenings.'},
 {name:'A little more structure',subtitle:'A different silhouette',products:['p08','p07','p03'],price:159,fit:84,style:87,probability:.65,issue:'fit',tradeoff:'The requested sizes match, but the trouser silhouette feels more structured than your selected lounge looks.'},
 {name:'The throwback track set',subtitle:'A style alternative',products:['p04','p11','p10'],price:146,fit:90,style:54,probability:.41,issue:'style',tradeoff:'The track pant introduces a sportier, retro direction. It is less aligned with your quiet lounge edit.'},
 {name:'The full lounge rotation',subtitle:'More pieces, near your limit',products:['p08','p04','p02','p03'],price:199,fit:96,style:94,probability:.62,issue:'coverage',tradeoff:'More pieces and two top layers, with less budget left over. Every item still matches your requested size.'},
] as const;

export function initialOffers(profile:Profile,rules:Rules):{bundles:Bundle[];payload:BundlePayload;context:BuyerContext;check:ReturnType<typeof validateBundlePayload>} {
 const context=buyerContext(profile);
 const bundles:Bundle[]=templates.map((template,i)=>{
  const skus=template.products.slice(0,rules.maxItems).map(id=>skuFor(id,profile));
  const items_total=skus.reduce((sum,sku)=>sum+findProduct(sku).price,0);
  const floor=Math.ceil(items_total*Math.max(.6,1-rules.maxDiscount/100));
  const price=Math.max(floor,Math.min(items_total,template.price,profile.budget));
  const priceScore=Math.max(1,Math.min(99,Math.round(98-(price/profile.budget)*12)));
  return {id:'b'+(i+1),name:template.name,subtitle:template.subtitle,skus,images:skus.map(sku=>findProduct(sku).image),items_total,price,scores:{price:priceScore,fit:template.fit,style:template.style},probability:template.probability,reason:skus.map(sku=>findProduct(sku).name).join(' + ')+'. '+template.tradeoff,tradeoff:template.tradeoff,issue:template.issue};
 });
 const payload={bundles:bundles.map(wireBundle)};
 return {bundles,payload,context,check:validateBundlePayload(payload,context,inventory,rules.maxItems,rules.maxDiscount)};
}
export function buyerRatings(bundles:Bundle[]):RatingsPayload{return {ratings:bundles.map(bundle=>({id:bundle.id,probability:bundle.probability,reason:bundle.reason}))};}

export function sellerAnalysis(bundles:Bundle[],ratings:RatingsPayload):Analysis {
 const byId=new Map(ratings.ratings.map(rating=>[rating.id,rating]));
 const buckets:{color:Record<string,number[]>;category:Record<string,number[]>;style:Record<string,number[]>}={color:{},category:{},style:{}};
 for(const bundle of bundles){const probability=byId.get(bundle.id)!.probability;
  for(const dimension of ['color','category'] as const)for(const value of new Set(bundle.skus.map(sku=>findProduct(sku)[dimension])))(buckets[dimension][value]??=[]).push(probability);
  if(bundle.issue==='style')(buckets.style.retro??=[]).push(probability);
 }
 const attribute_avgs=Object.fromEntries(Object.entries(buckets).map(([dimension,values])=>[dimension,Object.fromEntries(Object.entries(values).map(([value,numbers])=>[value,numbers.reduce((a,b)=>a+b,0)/numbers.length]))])) as Analysis['attribute_avgs'];
 const item_checks:Analysis['item_checks']=[];
 for(const bundle of bundles.filter(bundle=>byId.get(bundle.id)!.probability<.5))for(const sku of bundle.skus){const hurts=findProduct(sku).name==='Track pant';item_checks.push({bundle:bundle.id,sku,verdict:hurts?'hurts':'neutral',dimension:hurts?'style':'none',note:hurts?'Retro track styling is less aligned with the selected lounge looks.':'This piece appears in other, better-rated offers.'});}
 const votes=item_checks.filter(item=>item.verdict==='hurts').length;
 const confirmed=votes>0&&(attribute_avgs.style.retro??1)<.5;
 const drop_skus=confirmed?[...new Set(item_checks.filter(item=>item.verdict==='hurts').map(item=>item.sku))]:[];
 const keep_skus=[...new Set(bundles.filter(bundle=>byId.get(bundle.id)!.probability>=.5).flatMap(bundle=>bundle.skus))].filter(sku=>!drop_skus.includes(sku));
 return {avg:ratings.ratings.reduce((sum,rating)=>sum+rating.probability,0)/ratings.ratings.length,attribute_avgs,item_checks,works:Object.entries(attribute_avgs.color).filter(([,average])=>average>=.5).map(([value,avg_prob])=>({type:'color',value,avg_prob})),fails:votes?[{type:'style',value:'retro',avg_prob:attribute_avgs.style.retro??0,votes,confirmed}]:[],keep_skus,drop_skus,main_issue:votes?'style':'none'};
}
export function finalOffer(profile:Profile,rules:Rules,bundles:Bundle[],ratings:RatingsPayload,analysis:Analysis):{bundle:Bundle;payload:FinalPayload;check:ReturnType<typeof validateFinalPayload>} {
 const best=[...ratings.ratings].sort((a,b)=>b.probability-a.probability)[0];
 const original=bundles.find(bundle=>bundle.id===best.id)!;
 const crew=skuFor('p04',profile);
 let skus=original.skus.filter(sku=>!analysis.drop_skus.includes(sku));
 const hoodie=skuFor('p01',profile);
 if(skus.includes(hoodie)&&analysis.keep_skus.includes(crew))skus=skus.map(sku=>sku===hoodie?crew:sku);
 skus=skus.filter(sku=>analysis.keep_skus.includes(sku));
 const items_total=skus.reduce((sum,sku)=>sum+findProduct(sku).price,0);
 const price=Math.max(Math.ceil(items_total*Math.max(.6,1-rules.maxDiscount/100)),Math.min(149,items_total,profile.budget));
 const revised=original.skus.includes(hoodie)&&skus.includes(crew);
 const why='Based on '+best.id+' ('+Math.round(best.probability*100)+'% estimated buy chance): '+(revised?'swap the hooded layer for a crewneck, retain the neutral basics':'retain the strongest pieces from your preferred offer')+(analysis.drop_skus.length?', and leave out the low-rated pieces.':'.');
 const bundle:Bundle={...original,id:'final',name:'Your everyday edit',subtitle:'Refined by Sunday Theory',skus,images:skus.map(sku=>findProduct(sku).image),items_total,price,probability:.88,scores:{price:96,fit:97,style:98},reason:why,tradeoff:skus.map(sku=>findProduct(sku).name).join(' + ')+'. Your requested sizes, shaped by the five initial ratings.',issue:'none'};
 const payload={final:{...wireBundle(bundle),savings:items_total-price,why}};
 return {bundle,payload,check:validateFinalPayload(payload,buyerContext(profile),inventory,rules.maxItems,rules.maxDiscount,analysis.drop_skus)};
}
export function buyerDecision(bundle:Bundle,accept:boolean):Decision {return {decision:accept?'accept':'reject',probability:accept?bundle.probability:0,reason:accept?'Matches the requested sizes and style, with a '+bundle.price+' dollar total within budget.':'Buyer rejected the final offer.'};}
