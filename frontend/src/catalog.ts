import inventoryData from './data/inventory.json' with {type:'json'};
import productMetaData from './data/product-meta.json' with {type:'json'};
import type {InventoryItem,WireBundle} from './contracts';
import type {Quote,ReturnWindow} from './pricing';

export const inventory:InventoryItem[]=inventoryData;
export type ProductMeta={skus:string[];fit:string;styles:string[];gender:string;group:'top'|'bottom'|'accessory';displayCategory:string;sourceAsset:string};
export const productMeta=productMetaData as Record<string,ProductMeta>;
export type Product=InventoryItem & {id:string;fabric:string;fit:string;styles:string[];sizes:string[];gender:string;group:string};
const metadataFor=(sku:string)=>Object.values(productMeta).find(meta=>meta.skus.includes(sku))!;
export const skuCatalog:Product[]=inventory.map(item=>{
 const meta=metadataFor(item.sku);
 return {...item,id:item.sku,fabric:item.material,fit:meta.fit,styles:meta.styles,sizes:[item.size],gender:meta.gender,group:meta.group};
});
export const catalog:Product[]=Object.entries(productMeta).map(([id,meta])=>{
 const records=inventory.filter(item=>meta.skus.includes(item.sku));
 const representative=records.find(item=>item.size==='M')||records[0];
 return {...representative,id,fabric:representative.material,fit:meta.fit,styles:meta.styles,sizes:records.filter(item=>item.stock>0).map(item=>item.size),stock:records.reduce((sum,item)=>sum+item.stock,0),gender:meta.gender,group:meta.group};
});
export const findProduct=(id:string)=>skuCatalog.find(item=>item.sku===id)||catalog.find(item=>item.id===id)!;
export const imageUrl=(filename:string)=>filename.startsWith('/')?filename:'/images/'+filename;
export const styles = [
 {name:'Casual',desc:'Easy, everyday staples',image:'look-grey'},
 {name:'Athletic',desc:'Comfort that moves with you',image:'athletic'},
 {name:'Streetwear',desc:'Bolder shapes. A little edge.',image:'street'},
 {name:'Coastal',desc:'Light layers, slower days',image:'look-shorts'},
 {name:'Business casual',desc:'A little more put-together',image:'casual'},
 {name:'Formal',desc:'For the occasion',image:'formal'},
];
export const looks = [
 {id:'l1',name:'The soft set',desc:'Tonal layers · relaxed fit',image:'look-soft',tags:['Minimal','Relaxed','Cotton']},
 {id:'l2',name:'Off-duty essentials',desc:'Clean basics · easy movement',image:'look-grey',tags:['Minimal','Relaxed','Breathable']},
 {id:'l3',name:'A lighter day',desc:'Easy shorts · neutral palette',image:'look-shorts',tags:['Minimal','Loose','Lightweight']},
 {id:'l4',name:'Street rotation',desc:'Structured layers · darker tones',image:'street',tags:['Expressive','Loose','Layered']},
 {id:'l5',name:'Ready to move',desc:'Sporty basics · tapered fit',image:'athletic',tags:['Sporty','Regular','Tapered']},
 {id:'l6',name:'Everyday layers',desc:'Classic shapes · casual texture',image:'trouser',tags:['Classic','Regular','Layered']},
];

/** `deliveryDays`: wants the clothes within this many days. `returnWindow`: how long the return guarantee should run. */
export type Profile={styles:string[];looks:string[];location:string;occasions:string;budget:number;topSize:string;bottomSize:string;fit:string;notes:string;neededBy:string;deliveryDays:number;returnsNote:string;returnWindow:ReturnWindow};
export const defaultProfile:Profile={styles:[],looks:[],location:'Los Angeles',occasions:'Working from home, coffee runs, and relaxed weekends',budget:200,topSize:'M',bottomSize:'M',fit:'Relaxed',notes:'',neededBy:'',deliveryDays:7,returnsNote:'',returnWindow:'2 months'};
export type Rules={maxItems:number;maxDiscount:number};
export type Issue='none'|'value'|'fit'|'style'|'delivery'|'returns';
export type Bundle=WireBundle & {name:string;subtitle:string;quote:Quote;scores:{price:number;fit:number;style:number;delivery:number;returns:number};probability:number;reason:string;tradeoff:string;issue:Issue};
