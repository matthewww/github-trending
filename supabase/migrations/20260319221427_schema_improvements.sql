drop view if exists today_trending;

alter table repositories
  rename column stars to stars_today;

alter table repositories
  drop column url;

alter table repositories
  add column total_stars integer,
  add column forks integer;

create view today_trending as
  select repo_name, language, stars_today, total_stars, forks, rank
  from repositories
  where collected_date = current_date
  order by rank;
