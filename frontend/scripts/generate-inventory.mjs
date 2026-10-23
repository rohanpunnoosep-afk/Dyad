import { mkdir, writeFile, copyFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const frontend = fileURLToPath(new URL('../', import.meta.url));
// Explicit per-size demo counts. These are seed values, not live retailer stock.
const apparelStock = { S: 3, M: 3, L: 3, XL: 3 };
const seeds = [
  ['p01','HDY-01-GR','Cloud cotton hoodie','hoodie','Heather grey','85% cotton, 15% polyester',68,'Relaxed',['Casual','Athletic','Loungewear'],'hoodie','top',apparelStock,'Hoodies'],
  ['p02','PNT-01-TP','Everyday lounge jogger','pants','Taupe','88% polyester, 12% elastane',58,'Relaxed',['Casual','Athletic','Loungewear'],'jogger','bottom',apparelStock,'Pants'],
  ['p03','TEE-01-WH','Essential cotton tee','tee','White','100% cotton',32,'Regular',['Casual','Loungewear'],'white-tee','top',apparelStock,'T-shirts'],
  ['p04','SWE-01-WH','Soft-touch crewneck','sweatshirt','White','80% cotton, 20% polyester',62,'Loose',['Casual','Loungewear'],'crewneck','top',apparelStock,'Sweatshirts'],
  ['p05','SRT-01-OT','Sunday lounge short','shorts','Oat','95% cotton, 5% elastane',44,'Loose',['Casual','Athletic','Loungewear'],'shorts','bottom',apparelStock,'Shorts'],
  ['p06','TEE-02-BK','Graphic cotton tee','tee','Black','100% cotton',38,'Loose',['Streetwear','Casual'],'black-tee','top',apparelStock,'T-shirts'],
  ['p07','PNT-02-OL','Relaxed cotton trouser','pants','Olive','100% cotton',56,'Relaxed',['Casual','Loungewear'],'trouser','bottom',apparelStock,'Pants'],
  ['p08','HDY-02-TP','Zip-through lounge jacket','hoodie','Taupe','65% cotton, 35% polyester',72,'Relaxed',['Casual','Athletic','Loungewear'],'zip-hoodie','top',apparelStock,'Hoodies'],
  ['p09','SOC-01-CR','Patterned crew socks','socks','Cream & red','80% cotton, 18% polyester, 2% elastane',16,'Regular',['Streetwear','Casual'],'socks','accessory',{ OS: 12 },'Accessories'],
  ['p10','TEE-03-GR','Cotton lounge tee','tee','Light grey','100% cotton',36,'Relaxed',['Casual','Athletic','Loungewear'],'slate-tee','top',apparelStock,'T-shirts'],
  ['p11','PNT-03-GR','Track pant','pants','Heather grey','90% polyester, 10% elastane',64,'Regular',['Athletic'],'athletic','bottom',apparelStock,'Pants'],
  ['p12','SRT-02-OT','Everyday lounge short','shorts','Oat','95% cotton, 5% elastane',42,'Regular',['Casual','Athletic','Loungewear'],'shorts','bottom',apparelStock,'Shorts'],
  ['p13','JNS-01-IN','Classic straight jean','jeans','Indigo','100% cotton',78,'Regular',['Streetwear','Casual'],'jeans','bottom',apparelStock,'Pants'],
  ['p14','SHT-01-WH','Classic dress shirt','shirt','White','100% cotton',74,'Regular',['Business casual','Formal'],'shirt','top',apparelStock,'Shirts'],
  ['p15','JKT-01-NV','Tailored check blazer','jacket','Navy check','55% wool, 45% polyester',148,'Regular',['Formal','Business casual'],'blazer','top',{ S: 1, M: 2, L: 2, XL: 1 },'Jackets'],
  ['p16','JKT-02-IN','Denim jacket','jacket','Indigo','100% cotton',88,'Loose',['Streetwear','Casual'],'overshirt','top',{ S: 2, M: 2, L: 2, XL: 2 },'Jackets'],
  ['p17','HDY-03-NV','Weekend fleece hoodie','hoodie','Navy','Cotton-polyester fleece',64,'Regular',['Casual','Athletic','Loungewear'],'navy-hoodie','top',apparelStock,'Hoodies'],
  ['p18','HDY-04-GR','Loopback zip hoodie','hoodie','Light grey','Cotton loopback',76,'Relaxed',['Casual','Loungewear'],'grey-zip','top',apparelStock,'Hoodies'],
  ['p19','HDY-05-BU','Relaxed pullover hoodie','hoodie','Burgundy','Cotton-blend fleece',66,'Loose',['Streetwear','Casual','Loungewear'],'burgundy-hoodie','top',apparelStock,'Hoodies'],
  ['p20','SWE-02-GN','Forest crewneck','sweatshirt','Forest green','Cotton-blend fleece',58,'Relaxed',['Casual','Loungewear'],'green-crew','top',apparelStock,'Sweatshirts'],
  ['p21','SWE-03-SD','Everyday fleece crew','sweatshirt','Sand','Cotton-polyester fleece',54,'Regular',['Casual','Athletic','Loungewear'],'sand-crew','top',apparelStock,'Sweatshirts'],
  ['p22','PNT-04-BK','Soft stretch lounge pant','pants','Black','Polyester-elastane jersey',52,'Relaxed',['Casual','Loungewear'],'black-lounge','bottom',apparelStock,'Pants'],
  ['p23','TEE-04-BG','Neutral cotton tee','tee','Beige','100% cotton',28,'Regular',['Casual','Loungewear'],'beige-tee','top',apparelStock,'T-shirts'],
  ['p24','TEE-05-BK','Lightweight performance tee','tee','Black','100% polyester',34,'Regular',['Athletic'],'performance-tee','top',apparelStock,'T-shirts'],
  ['p25','SRT-03-BL','Woven training short','shorts','Blue','Polyester-spandex woven',40,'Regular',['Athletic','Casual'],'blue-active-short','bottom',apparelStock,'Shorts'],
  ['p26','POL-01-NV','Everyday jersey polo','polo','Navy','Cotton-blend jersey',48,'Regular',['Casual','Business casual'],'navy-polo','top',apparelStock,'Shirts'],
  ['p27','SHT-02-BL','Breezy linen shirt','shirt','Blue','100% linen',72,'Regular',['Coastal','Casual','Business casual'],'blue-linen','top',apparelStock,'Shirts'],
  ['p28','PNT-05-TN','Straight-leg chino','pants','Tan','Cotton twill',64,'Regular',['Casual','Business casual'],'tan-chino','bottom',apparelStock,'Pants'],
  ['p29','JKT-03-BK','Everyday bomber jacket','jacket','Black','Polyester shell',96,'Regular',['Streetwear','Casual'],'black-bomber','top',{ S: 2, M: 3, L: 3, XL: 2 },'Jackets'],
  ['p30','JKT-04-OL','Cotton utility overshirt','jacket','Olive','Cotton-rich canvas',82,'Relaxed',['Streetwear','Casual'],'olive-overshirt','top',{ S: 2, M: 3, L: 3, XL: 2 },'Jackets'],
  ['p31','SNK-01-WH','Clean low-top sneaker','sneakers','White','Leather upper, rubber sole',90,'Regular',['Casual','Streetwear'],'white-sneaker','accessory',{ '8': 2, '9': 2, '10': 3, '11': 2, '12': 2 },'Footwear'],
  ['p32','CAP-01-BK','Classic baseball cap','cap','Black','Cotton twill',22,'Adjustable',['Casual','Athletic','Streetwear'],'black-cap','accessory',{ OS: 12 },'Accessories'],
];

const inventory = [];
const metadata = {};
for (const [id, prefix, name, category, color, material, price, fit, styles, asset, group, sizeStock, displayCategory] of seeds) {
  const skus = [];
  for (const [size, stock] of Object.entries(sizeStock)) {
    const sku = `${prefix}-${size}`;
    const image = `${sku}.jpg`;
    inventory.push({ sku, name, category, color, material, size, price, stock, image });
    skus.push(sku);
    await copyFile(path.join(frontend,'public/images',`${asset}.jpg`), path.join(frontend,'public/images',image));
  }
  metadata[id] = { skus, fit, styles, gender: 'Menswear', group, displayCategory, sourceAsset: `${asset}.jpg` };
}
await mkdir(path.join(frontend,'src/data'), { recursive: true });
await writeFile(path.join(frontend,'src/data/inventory.json'), JSON.stringify(inventory,null,2)+'\n');
await writeFile(path.join(frontend,'src/data/product-meta.json'), JSON.stringify(metadata,null,2)+'\n');

console.log(`Generated ${inventory.length} SKU records across ${seeds.length} products.`);

