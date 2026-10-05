const assert = require('node:assert/strict');
const test = require('node:test');
const {filterMedia, mediaSize} = require('../WebApp/static/media-library.js');

test('library search combines type, readable title, filename, and message references', () => {
  const photo = {type:'photo',title:'ФОТО из пересылки',filename:'sha256_a.jpg',messages:[{cid:947},{cid:42}]};
  const audio = {type:'audio',title:'Artist — Song',filename:'music.m4a',messages:[{cid:2}]};
  const items = [photo,audio];
  assert.deepEqual(filterMedia(items,'all','947'),[photo]);
  assert.deepEqual(filterMedia(items,'photo',' фото '),[photo]);
  assert.deepEqual(filterMedia(items,'audio','фото'),[]);
  assert.deepEqual(filterMedia(items,'all','sha256_a'),[photo]);
  assert.deepEqual(filterMedia(items,'all',''),items);
  assert.deepEqual(filterMedia([], 'all', ''), []);
});

test('file sizes support zero, small files, and multi-gigabyte media', () => {
  assert.equal(mediaSize(0),'0 Б');
  assert.equal(mediaSize(1024),'1 КБ');
  assert.equal(mediaSize(2 * 1024 ** 3),'2 ГБ');
});
