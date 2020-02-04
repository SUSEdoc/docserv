var body = '';
var productSelect = '';
var versionSelect = '';

var path = basePath + 'docserv/data/'
var productData = 'no_data';
var productHashes = [];

function loadJSON(path, success, error) {
  var xhr = new XMLHttpRequest();
  xhr.onreadystatechange = function() {
    if (xhr.readyState === XMLHttpRequest.DONE) {
      if (xhr.status === 200) {
        if (success) {
          success(JSON.parse(xhr.responseText));
        }
      }
      else if (error) {
        error(xhr);
      }
    }
  }
  xhr.open("GET", path, true); // helpful later, to avoid caching issues?: + '?time=' + Date.now()
  // Response type JSON does not work for me somehow because then I need to
  // use xhr.response instead of xhr.responseText above.
  xhr.responseType = 'text';
  xhr.send();
}

function getProductData() {
  var jsonFile = 'product.json';
  if (pageRole == 'unsupported') {
    jsonFile = 'unsupported.json';
  };
  loadJSON(path + jsonFile,
    function (data) {
        productData = data;
        if (document.readyState === 'complete') {
          dsInit();
        }
        else {
          window.addEventListener("load", dsInit, false);
        };
    },
    function (xhr) {
      console.error(xhr);
      // do something to tell the user.
    }
  );
}


function populateProductSelect() {
  productSelect.removeChild( productSelect.getElementsByClassName( 'ds-select-instruction' )[0] );
  var productlinelist = Object.keys(productData.productline);
  for (var i = 0; i < productlinelist.length; i++) {
    var link = document.createElement('a');
    link.setAttribute( 'href', '#' + productlinelist[ i ] );
    link.textContent = productData.productline[ Object.keys( productData.productline )[ i ] ];
    productSelect.appendChild( link );
    productHashes.push( '#' + productlinelist[ i ] );
    link.addEventListener('click',function(){
        var links = productSelect.getElementsByClassName( 'ds-selected' );
        for (var i = 0; i < links.length; i++) {
          links[i].classList.remove( 'ds-selected' );
        }
        this.classList.add( 'ds-selected' );
        populateVersionSelect(this.hash.substr(1));
    });
  }
}

function populateVersionSelect(productid) {
  var instruction = versionSelect.getElementsByClassName( 'ds-select-instruction' )
  if ( instruction[0] ){
    instruction[0].remove();
  }
  existingLinks = versionSelect.getElementsByTagName( 'a' );
  if ( existingLinks[0] ) {
    // go backwards, to avoid giving the browser hiccups
    for (var i = existingLinks.length - 1; i >= 0; i--) {
      existingLinks[i].parentElement.removeChild(existingLinks[i]);
    }
  }
  var versionlist = Object.keys(productData.product[productid]);
  for (var i = 0; i < versionlist.length; i++) {
    var link = document.createElement('a');
    link.setAttribute( 'href', normalizePath(pageLanguage + '/' + versionlist[ i ] + '/'));
    var selectedProduct = productData.product[ productid ][ Object.keys( productData.product[productid] )[ i ] ]
    s_linkText = selectedProduct['name'] + ' ' + selectedProduct["version"];
    if (selectedProduct.lifecycle == 'beta' || selectedProduct.lifecycle == 'unpublished') {
      // FIXME: L10n for beta string
      s_linkText = s_linkText + ' (' + selectedProduct.lifecycle + ')';
    };
    link.textContent = s_linkText;
    versionSelect.appendChild( link );
  }
}

function loadDocSet(setid) {
  loadJSON(path + setid + '/' + 'setdata.json',
    function (data) {
        docSetData = data;
        if (document.readyState === 'complete') {
          dsInit();
        }
        else {
          window.addEventListener("load", dsInit, false);
        };
    },
    function (xhr) {
      console.error(xhr);
      // do something to tell the user.
    }
  );
}

function populateDocSet() {
  var e_docSetWrap = document.getElementById('docsetwrap');
  if (docSetData.lifecycle == 'beta') {
    body.classList.add('ds-beta-documentation');
  }
  else if (docSetData.lifecycle == 'unpublished') {
    body.classList.add('ds-unpublished-documentation');
  };
  var s_product = docSetData.productname + ' ' + docSetData.version;
  if (docSetData.lifecycle == 'beta' || docSetData.lifecycle == 'unpublished' || docSetData.lifecycle == 'unsupported') {
    // FIXME: L10n for beta string
    s_product = s_product + ' (' + docSetData.lifecycle + ')';
  };
  var e_title = document.createElement('h2');
  e_title.classList.add('ds-docset-title');
  e_title.textContent = s_product;
  e_docSetWrap.appendChild(e_title);
  var e_desc = document.createElement('div');
  e_desc.classList.add('ds-docset-desc');
  desc_text = docSetData.description[0].description;
  for (var l = 0; l < docSetData.description.length; l++) {
    if (docSetData.description[l].lang == pageLanguage) {
      desc_text = docSetData.description[l].description;
    };
  };
  e_desc.innerHTML = desc_text;
  e_docSetWrap.appendChild(e_desc);

  if (docSetData.archive[0]) {
    var e_archives = document.createElement('div');
    e_archives.classList.add('ds-docset-archive-list');
    var e_archiveDefault = document.createElement('a');
    e_archiveDefault.classList.add('ds-docset-archive-link');
    e_archiveDefault.setAttribute('href', normalizePath(docSetData.archive[0].zip));
    // FIXME: l10n for "Download as"!
    e_archiveDefault.textContent = 'Download Documentation as Zip' + ' (' + docSetData.archive[0].lang + ', complete)';

    if (pageLanguage != docSetData.archive[0].lang) {
      for (var l = 0; l < docSetData.archive.length; l++) {
        if (pageLanguage == docSetData.archive[l].lang) {
          var e_archiveTranslation = document.createElement('a');
          e_archiveTranslation.classList.add('ds-docset-archive-link');
          e_archiveTranslation.setAttribute('href', normalizePath(docSetData.archive[0].zip));
          // FIXME: l10n for "Download as"!
          e_archiveTranslation.textContent = 'Download Documentation as Zip' + ' (' + docSetData.archive[l].lang + ', may be incomplete)';
          e_archives.appendChild(e_archiveTranslation);
          // FIXME: this ugly vvv
          e_archives.appendChild(document.createElement('br'));
        }
      }
    }
     e_archives.appendChild(e_archiveDefault);
     e_docSetWrap.appendChild(e_archives);
  }


  for (var i = 0; i < docSetData.category.length; i++) {
    var e_cat = document.createElement('div');
    e_cat.id = docSetData.category[i].category;
    e_cat.classList.add('ds-docset-category');
    e_docSetWrap.appendChild(e_cat);
    if (docSetData.category[i].category != false) {
      var e_catTitle = document.createElement('h3');
      e_catTitle.classList.add('ds-docset-category-title');
      var e_catDesc = document.createElement('div');
      e_catTitle.classList.add('ds-docset-category-desc');
      cat_text = docSetData.category[i].title[0].title;
      cat_desc_text = docSetData.category[i].title[0].description;
      for (var l = 0; l < docSetData.category[i].title.length; l++) {
        if (docSetData.category[i].title[l].lang == pageLanguage) {
          cat_text = docSetData.category[i].title[l].title;
          if (docSetData.category[i].title[l].description != false) {
            cat_desc_text = docSetData.category[i].title[l].description;
          }
        };
      };
      e_catTitle.textContent = cat_text;
      e_cat.appendChild(e_catTitle);
      if (cat_desc_text != false) {
        e_catDesc.innerHTML = cat_desc_text;
        e_cat.appendChild(e_catDesc);
      };
    }
    else {
      e_cat.classList.add('ds-category-no-title');
    };
    var e_documentTable = document.createElement('table');
    e_documentTable.classList.add('ds-docset-table');
    e_cat.appendChild(e_documentTable);
    for (var j = 0; j < docSetData.category[i].document.length; j++) {
      var e_documentRow = document.createElement('tr');
      e_documentTable.appendChild(e_documentRow);

      var e_documentTitle = document.createElement('td');
      e_documentTitle.classList.add('ds-docset-table-title');
      doc_title_text = docSetData.category[i].document[j][0].title;
      var use_lang = 0;
      for (var l = 0; l < docSetData.category[i].document[j].length; l++) {
        if (docSetData.category[i].document[j][l].lang == pageLanguage) {
          doc_title_text = docSetData.category[i].document[j][l].title;
          use_lang = l;
        };
      };
      e_documentTitle.textContent = doc_title_text;
      e_documentRow.appendChild(e_documentTitle);
      var e_documentLanguage = document.createElement('td');
      e_documentLanguage.classList.add('ds-docset-table-language');
      if (docSetData.category[i].document[j].length > 1 &&
          docSetData.category[i].document[j][0]['lang-switchable'] == true) {
        var e_languageSelector = document.createElement('select');
        e_documentLanguage.classList.add('ds-has-language-selector');
        e_languageSelector.classList.add('ds-docset-table-lang-select');
        e_documentLanguage.appendChild(e_languageSelector);
        for (var k = 0; k < docSetData.category[i].document[j].length; k++) {
          var e_languageChoice = document.createElement('option');
          e_languageChoice.setAttribute( 'value', docSetData.category[i].document[j][k].lang );
          e_languageChoice.setAttribute( 'data-category', i);
          e_languageChoice.setAttribute( 'data-doc', j);
          e_languageChoice.setAttribute( 'data-lang', k);
          if (k == use_lang) {
            e_languageChoice.setAttribute( 'selected', '')
          };
          e_languageChoice.textContent = docSetData.category[i].document[j][k].lang;
          e_languageSelector.appendChild(e_languageChoice);
        };
        e_languageSelector.addEventListener('change',function(){
          // FIXME: this parent.parent.parent thing is ugly.
          var e_documentFormats = this.parentElement.parentElement.getElementsByClassName('ds-docset-table-formats')[0];
          for (var m = e_documentFormats.getElementsByTagName('a').length - 1; m >= 0; m--) {
            e_documentFormats.removeChild(e_documentFormats.getElementsByTagName('a')[m]);
          }
          var i = this.options[this.selectedIndex].getAttribute('data-category');
          var j = this.options[this.selectedIndex].getAttribute('data-doc');
          var l = this.options[this.selectedIndex].getAttribute('data-lang');
          //var l = this.options[this.selectedIndex].text; // for debugging data-lang
          buildFormatList(e_documentFormats, i, j, l);
        });
      }
      else {
        e_documentLanguage.textContent = docSetData.category[i].document[j][use_lang].lang;
      };
      e_documentRow.appendChild(e_documentLanguage);
      var e_documentFormats = document.createElement('td');
      e_documentFormats.classList.add('ds-docset-table-formats');
      e_documentRow.appendChild(e_documentFormats);
      buildFormatList(e_documentFormats, i, j, use_lang);

      var e_documentDate = document.createElement('td');
      if (docSetData.category[i].document[j][use_lang].date != false) {
        e_documentDate.classList.add('ds-docset-table-date');
        e_documentDate.textContent = convertTime(docSetData.category[i].document[j][use_lang].date);
        e_documentRow.appendChild(e_documentDate);
      }
      else {
        e_documentFormats.setAttribute('colspan', '2');
        e_documentFormats.classList.add('no-date');
      }
    };
  }
}

function buildFormatList(e_documentFormats, i, j, l) {
  var formatList = docSetData.category[i].document[j][l].format;
  for (var k = 0; k < Object.keys(formatList).length; k++) {
    var e_documentLink = document.createElement('a');
    e_documentLink.classList.add('ds-docset-table-link');
    e_documentLink.textContent = Object.keys(formatList)[k];
    e_documentLink.setAttribute( 'href', normalizePath(formatList[ Object.keys(formatList)[k] ]) );
    e_documentFormats.appendChild(e_documentLink);
  };
}

// via https://stackoverflow.com/questions/847185
function convertTime(unixTime){
  var a = new Date(unixTime * 1000);
  var year = a.getFullYear();
  var month = ("0" + (a.getMonth()+1)).slice(-2);
  var date = ("0" + a.getDate()).slice(-2);
  // var hour = a.getHours();
  // var min = a.getMinutes();
  // var sec = a.getSeconds();
  var time = year + '-' + month + '-' + date;
  return time;
}

function normalizePath(potentialPath) {
  if (! (potentialPath.lastIndexOf('https://', 0) === 0 ||
         potentialPath.lastIndexOf('http://', 0) === 0  ||
         potentialPath.lastIndexOf('mailto:', 0) === 0  ||
         potentialPath.lastIndexOf('ftp://', 0) === 0)  ||
         potentialPath.lastIndexOf('//', 0) === 0) {
    if (typeof(omitPathComponent) === 'string') {
      var omitPathRegex = new RegExp('^' + omitPathComponent);
      potentialPath = potentialPath.replace(omitPathRegex, '');
    };
    return basePath + potentialPath;
  }
  else {
    return potentialPath;
  };
}

function setProductFromHash() {
  if (location.hash && productHashes.indexOf(location.hash) > -1 ) {
    // largely copypasta from above
    var links = productSelect.getElementsByClassName( 'ds-selected' );
    for (var i = 0; i < links.length; i++) {
      links[i].classList.remove( 'ds-selected' );
    }
    productSelect.querySelectorAll('[href="' + location.hash + '"]')[0].classList.add( 'ds-selected' );
    populateVersionSelect(location.hash.substr(1));
  };
}


function dsInit() {
  body = document.getElementsByTagName( 'body' )[0];
  if (pageRole == 'main' | pageRole == 'unsupported') {
    productSelect = document.getElementById( 'ds-product-select' );
    versionSelect = document.getElementById( 'ds-version-select' );

    if ( typeof(productData) === 'object' ) {
      populateProductSelect();
    }

    setProductFromHash();
    window.addEventListener("hashchange", setProductFromHash, false);
  }
  else if (pageRole == 'product') {
    if ( typeof(docSetData) === 'object' ) {
      populateDocSet();
    }
  };

}

if (pageRole == 'main' | pageRole == 'unsupported') {
  getProductData();
}
else if (pageRole == 'product') {
  setid = pageProduct + '/' + pageDocSet;
  loadDocSet(setid);
};
