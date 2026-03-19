alter table repositories
  add column collected_date date not null default current_date;

drop index if exists idx_repo_date_unique;

create unique index idx_repo_date_unique on repositories(repo_name, collected_date);

drop view if exists today_trending;

create view today_trending as
  select repo_name, url, language, stars, rank
  from repositories
  where collected_date = current_date
  order by rank;
