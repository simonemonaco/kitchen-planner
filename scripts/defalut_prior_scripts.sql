INSERT INTO public.item_prior (
    name,
    category,
    typical_quantity,
    typical_unit,
    typical_shelf_life_days,
    default_location,
    picture,
    picture_source,
    source_product_url
) VALUES
('Mozzarella', 'Formaggi', 125, 'g', 10, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Mozzarella%20di%20bufala3.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q14088'),

('Pasta', 'Pasta', 500, 'g', 365, 'dispensa',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Pasta%20IMG%203985.JPG',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q178'),

('Riso', 'Cereali', 1, 'kg', 365, 'dispensa',
 'https://commons.wikimedia.org/wiki/Special:FilePath/White%2C%20Brown%2C%20Red%20%26%20Wild%20rice.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q5090'),

('Farro', 'Cereali', 500, 'g', 365, 'dispensa',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Farro2.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q1133342'),

('Melanzane', 'Verdura', 1, 'pz', 5, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Aubergine-Varianten.JPG',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q12533094'),

('Mele', 'Frutta', 1, 'kg', 30, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Assorted%20Red%20and%20Green%20Apples%202120px.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q89'),

('Pere', 'Frutta', 1, 'kg', 7, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Pears.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q13099586'),

('Fragole', 'Frutta', 250, 'g', 3, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Strawberries.JPG',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q13158'),

('Spaghetti', 'Pasta', 500, 'g', NULL, 'dispensa',
 'https://www.themealdb.com/images/ingredients/Spaghetti.png',
 'TheMealDB',
 'https://www.themealdb.com/ingredient/298-Spaghetti'),

('Tagliolini', 'Pasta', 250, 'g', NULL, 'dispensa',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Taglioni%20side.png',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q20046'),

('Gnocchi', 'Pasta', 500, 'g', 7, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Gnocchi%20di%20ricotta%20burro%20e%20salvia.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q20063'),

('Yogurt Greco', 'Latticini', 450, 'g', 14, 'frigo',
 'https://www.themealdb.com/images/ingredients/Greek%20Yogurt.png',
 'TheMealDB',
 'https://themealdb.com/ingredient/162-Greek-yogurt'),

('Latte', 'Latticini', 1, 'l', 7, 'dispensa',
 'https://www.themealdb.com/images/ingredients/Milk.png',
 'TheMealDB',
 'https://www.themealdb.com/ingredient/211-milk'),

('Mozzarella di Bufala', 'Formaggi', 125, 'g', 7, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Mozzarella.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q941068'),

('Gorgonzola', 'Formaggi', 200, 'g', 21, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Gorgonzola%201.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q209044'),

('Parmigiano Reggiano', 'Formaggi', 250, 'g', 90, 'frigo',
 'https://www.themealdb.com/images/ingredients/Parmigiano-Reggiano.png',
 'TheMealDB',
 'https://themealdb.com/ingredient/236-Parmigiano-Reggiano'),

('Provola', 'Formaggi', 250, 'g', 21, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Provole%20dei%20Nebrodi%20(appese).jpg',
 'Wikimedia Commons / Wikipedia',
 'https://it.wikipedia.org/wiki/Provola'),

('Cioccolato Fondente', 'Dolci', 100, 'g', NULL, 'dispensa',
 'https://www.themealdb.com/images/ingredients/Dark%20Chocolate.png',
 'TheMealDB',
 'https://themealdb.com/ingredient/417-Dark-Chocolate'),

('Panna', 'Latticini', 200, 'ml', 10, 'frigo',
 'https://www.themealdb.com/images/ingredients/Cream.png',
 'TheMealDB',
 'https://www.themealdb.com/ingredient/100-Cream'),

('Cioccolato Bianco', 'Dolci', 100, 'g', NULL, 'dispensa',
 'https://www.themealdb.com/images/ingredients/White%20Chocolate.png',
 'TheMealDB',
 'https://www.themealdb.com/ingredient/496-White-Chocolate'),

('Lievito per dolci', 'Dolci', 16, 'g', NULL, 'dispensa',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Backpulver%20RZ.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q29476'),

('Zucchero semolato', 'Dolci', 1, 'kg', NULL, 'dispensa',
 'https://www.themealdb.com/images/ingredients/Granulated%20Sugar.png',
 'TheMealDB',
 'https://themealdb.com/ingredient/160-Granulated-sugar'),

('Farina', 'Cereali', 1, 'kg', NULL, 'dispensa',
 'https://www.themealdb.com/images/ingredients/Flour.png',
 'TheMealDB',
 'https://www.themealdb.com/ingredient/137-Flour'),

('Pangrattato', 'Cereali', 250, 'g', NULL, 'dispensa',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Breadcrumb.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q658413'),

('Pane', 'Cereali', 500, 'g', 3, 'dispensa',
 'https://www.themealdb.com/images/ingredients/Bread.png',
 'TheMealDB',
 'https://www.themealdb.com/ingredient/35-Bread'),

('Succo di mirtillo', 'Frutta', 1, 'l', 7, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Cranberry%20juice.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q865448'),

('Marmellata di frutti rossi', 'Dolci', 350, 'g', 30, 'frigo',
 'https://www.themealdb.com/images/ingredients/Jam.png',
 'TheMealDB',
 'https://themealdb.com/ingredient/599-Jam'),

('Uova', 'Uova', 6, 'pz', 28, 'frigo',
 'https://www.themealdb.com/images/ingredients/Eggs.png',
 'TheMealDB',
 'https://www.themealdb.com/ingredient/123-Eggs'),

('Asparagi', 'Verdura', 500, 'g', 4, 'frigo',
 'https://www.themealdb.com/images/ingredients/Asparagus.png',
 'TheMealDB',
 'https://www.themealdb.com/ingredient/10-asparagus'),

('Peperoni', 'Verdura', 500, 'g', 7, 'frigo',
 'https://www.themealdb.com/images/ingredients/Green%20Pepper.png',
 'TheMealDB',
 'https://www.themealdb.com/ingredient/425-Green-Pepper'),

('Cipolla', 'Verdura', 1, 'pz', 30, 'dispensa',
 'https://www.themealdb.com/images/ingredients/Onion.png',
 'TheMealDB',
 'https://www.themealdb.com/ingredient/364-onion'),

('Aglio', 'Verdura', 1, 'pz', 60, 'dispensa',
 'https://www.themealdb.com/images/ingredients/Garlic.png',
 'TheMealDB',
 'https://www.themealdb.com/ingredient/149-garlic'),

('Pesche tabacchiere', 'Frutta', 500, 'g', 5, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Saturn%20peaches.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q2702783'),

('Albicocche', 'Frutta', 500, 'g', 5, 'frigo',
 'https://www.themealdb.com/images/ingredients/Apricot.png',
 'TheMealDB',
 'https://www.themealdb.com/ingredient/382-Apricot'),
 
('Vino rosso', 'Altro', 750, 'ml', NULL, 'dispensa',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Pouring%20a%20glass%20of%20red%20wine.tiff',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q1827'),

('Panini hamburger', 'Cereali', 4, 'pz', 5, 'dispensa',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Hamburger%20bun.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q117234715'),

('Tagliatelle', 'Pasta', 500, 'g', NULL, 'dispensa',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Dry%20tagliatelle%20pasta.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q20044'),

('Pesto alla genovese', 'Altro', 190, 'g', 7, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/BasilPesto.JPG',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q9896'),

('Pinsa romana', 'Cereali', 1, 'pz', 5, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Pinsa%20di%20Roma.jpg',
 'Wikidata / Wikimedia Commons',
 'https://www.wikidata.org/wiki/Q48034588'),

('Fetta di manzo', 'Carne', 250, 'g', 3, 'frigo',
 'https://commons.wikimedia.org/wiki/Special:FilePath/Raw%20beef%20slices.jpg',
 'Wikimedia Commons',
 'https://commons.wikimedia.org/wiki/File:Raw_beef_slices.jpg');

 