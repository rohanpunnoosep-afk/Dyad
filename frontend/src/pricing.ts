/** The seller's pricing policy. Mirrors middleman/pricing.py; keep the two in step.
 * price = items total × (1 − margin discount + shipping + rush + return guarantee) */
import type {InventoryItem} from './contracts.ts';

export type Shipping='standard'|'express'|'priority';
export type ReturnWindow='2 weeks'|'2 months'|'6 months';
export type RefundPct=30|75|100;

export const MARGIN_FLOOR_PCT=40;
export const MARGIN_DISCOUNT_SHARE=.5;
export const SHIPPING:Record<Shipping,number>={standard:0,express:6,priority:12};
export const SHIPPING_TIERS=Object.keys(SHIPPING) as Shipping[];
export const RETURN_WINDOWS:Record<ReturnWindow,number>={'2 weeks':4,'2 months':8,'6 months':14};
export const WINDOWS=Object.keys(RETURN_WINDOWS) as ReturnWindow[];
export const REFUND_PCTS:RefundPct[]=[30,75,100];
const RUSH:[number,number][]=[[2,6],[5,3]];

export type Quote={items_total:number;margin_pct:number;margin_discount_pct:number;shipping_pct:number;rush_pct:number;returns_pct:number;delivery_days:number;price:number};
const round1=(n:number)=>Math.round(n*10)/10;

export function aggregateMargin(items:InventoryItem[]):number {const total=items.reduce((s,i)=>s+i.price,0);return total?round1(items.reduce((s,i)=>s+i.price*i.margin_pct,0)/total):0}
export function marginDiscount(margin:number,cap:number):number {return round1(Math.min(cap,Math.max(0,(margin-MARGIN_FLOOR_PCT)*MARGIN_DISCOUNT_SHARE)))}
export function standardDays(items:InventoryItem[]):number {return Math.max(0,...items.map(i=>i.delivery_days))}
export function deliveryDays(items:InventoryItem[],shipping:Shipping):number {const base=standardDays(items);return shipping==='express'?Math.max(2,Math.ceil(base/2)):shipping==='priority'?Math.max(1,Math.ceil(base/4)):base}
export function rushPremium(wantedWithinDays?:number|null):number {if(wantedWithinDays==null)return 0;for(const [limit,pct] of RUSH)if(wantedWithinDays<=limit)return pct;return 0}
export function returnsPremium(window:ReturnWindow,refund:RefundPct):number {return Math.round(RETURN_WINDOWS[window]*refund)/100}

/** `maxDiscount` is the seller's cap on the margin-based discount, in percent. */
export function quote(items:InventoryItem[],shipping:Shipping,window:ReturnWindow,refund:RefundPct,wantedWithinDays:number|null|undefined,maxDiscount:number):Quote {
 const items_total=items.reduce((s,i)=>s+i.price,0);
 const margin_pct=aggregateMargin(items);
 const margin_discount_pct=marginDiscount(margin_pct,maxDiscount);
 const shipping_pct=SHIPPING[shipping],rush_pct=rushPremium(wantedWithinDays),returns_pct=returnsPremium(window,refund);
 const price=Math.round(items_total*(1+(shipping_pct+rush_pct+returns_pct-margin_discount_pct)/100));
 return {items_total,margin_pct,margin_discount_pct,shipping_pct,rush_pct,returns_pct,delivery_days:deliveryDays(items,shipping),price};
}
export const shippingLabel=(s:Shipping)=>s==='standard'?'Standard':s==='express'?'Express':'Priority';
