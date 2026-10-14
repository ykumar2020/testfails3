for(const button of document.querySelectorAll('[data-board]')){
  button.addEventListener('click',()=>{
    for(const tab of document.querySelectorAll('[data-board]'))tab.setAttribute('aria-selected',String(tab===button));
    for(const panel of document.querySelectorAll('.board'))panel.hidden=panel.id!==`board-${button.dataset.board}`;
  });
}
